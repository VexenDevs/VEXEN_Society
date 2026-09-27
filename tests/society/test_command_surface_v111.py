import ast
from pathlib import Path
from types import SimpleNamespace
import pytest
from app.society.command_surface import QUICK_COMMAND_PATHS,command_paths,simplify_commands
from app.config.settings import Settings

ROOT=Path(__file__).resolve().parents[2]

class Group:
    def __init__(self,name='society'):self.name=name;self.commands=[]
    def remove_command(self,name):
        found=next((x for x in self.commands if x.name==name),None)
        if found:self.commands.remove(found)
        return found


def declared_tree():
    source=ast.parse((ROOT/'app/society/associates.py').read_text(encoding='utf-8'))
    cog=next(x for x in source.body if isinstance(x,ast.ClassDef))
    groups={'society':Group()}
    for n in cog.body:
        if isinstance(n,ast.Assign) and isinstance(n.value,ast.Call) and ast.unparse(n.value.func)=='app_commands.Group':
            kw={k.arg:ast.literal_eval(k.value) for k in n.value.keywords if k.arg=='name'}
            name=n.targets[0].id
            if name=='society':continue
            groups[name]=Group(kw['name']);groups['society'].commands.append(groups[name])
    for n in cog.body:
        if not isinstance(n,(ast.AsyncFunctionDef,ast.FunctionDef)):continue
        for d in n.decorator_list:
            if isinstance(d,ast.Call) and isinstance(d.func,ast.Attribute) and d.func.attr=='command':
                name=next(ast.literal_eval(k.value) for k in d.keywords if k.arg=='name')
                groups[d.func.value.id].commands.append(SimpleNamespace(name=name))
    return groups['society']


def test_declared_surface_reduces_to_exact_twelve_fast_actions():
    tree=declared_tree();assert 'config estado' not in command_paths(tree)
    simplify_commands(tree);assert command_paths(tree)==QUICK_COMMAND_PATHS
    simplify_commands(tree);assert len(command_paths(tree))==12


def test_unknown_command_fails_surface_validation():
    tree=declared_tree();tree.commands.append(SimpleNamespace(name='unapproved'))
    with pytest.raises(RuntimeError):simplify_commands(tree)


def test_hook_prunes_after_logs_before_add_cog_and_sync():
    source=(ROOT/'app/bot/client.py').read_text(encoding='utf-8')
    assert source.index('society_log_service.setup(society_cog)')<source.index('simplify_commands(society_cog.society)')<source.index('await self.add_cog(society_cog)')<source.index('self.tree.sync(guild=guild)')
    logs=(ROOT/'app/society/logs.py').read_text(encoding='utf-8')
    setup=logs[logs.index('    async def setup('):logs.index('    async def ensure',logs.index('    async def setup('))] if '    async def ensure' in logs else logs
    assert 'self.register_commands(society_cog)' not in setup


def test_dashboard_url_is_https_and_no_credentials():
    assert Settings(_env_file=None).dashboard_url=='https://society.vexen.one'
    for url in ('http://insecure.example','javascript:bad','https://user:pass@example.org'):
        with pytest.raises(ValueError):Settings(_env_file=None,dashboard_url=url)


def test_delete_confirmation_and_owner_access_services_preserved():
    source=(ROOT/'app/society/associates.py').read_text(encoding='utf-8')
    assert 'DeleteSocietyView(' in source
    worker=(ROOT/'app/bot/control_jobs.py').read_text(encoding='utf-8')
    assert 'Solo OWNER puede modificar los roles administrativos' in worker
    assert 'configure_onboarding' in worker and 'set_config' in worker


def test_actual_discord_cog_tree_when_dependency_is_installed():
    pytest.importorskip('discord',reason='discord.py no está instalado en el entorno de validación; ejecutar el smoke local con requirements.txt.')
    pytest.importorskip('asyncpg',reason='asyncpg no está instalado en el entorno de validación.')
    from app.society.associates import SocietyCog
    import asyncio
    async def smoke():
        cog=SocietyCog(SimpleNamespace(db=None),Settings(_env_file=None,guild_id=123,owner_id=999))
        assert command_paths(cog.society)==QUICK_COMMAND_PATHS
        assert len(cog._dashboard_view().children)==1
    asyncio.run(smoke())
