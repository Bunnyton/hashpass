"""Labfile (spec 2026-11-02 §1а): docker-compose for Taskfiles -- machines + network + the task."""
import pytest

from hashpass.lab.parse import parse_labfile

_LAB = """\
lab net-hello:1

machine pc
  console
  build pc                 # pc/Taskfile
  net lan 10.0.0.10/24

machine web
  build web
  net lan 10.0.0.20/24

say "Hello"

stage
  solve curl -s http://web/
  check live on web grep -q GET /var/log/nginx/access.log
"""


def _with(machines: str, stages: str = 'say "x"\nstage\n  solve true\n') -> str:
    return "lab t:1\n" + machines + stages


_PC = "machine pc\n  console\n  build pc\n  net lan 10.0.0.10/24\n"


@pytest.mark.tier1
def test_the_example_parses() -> None:
    lab, recipe = parse_labfile(_LAB)
    assert (lab.name, lab.version) == ("net-hello", "1")
    assert [m.name for m in lab.machines] == ["pc", "web"]
    assert lab.console.name == "pc"
    assert [m.name for m in lab.nodes] == ["web"]
    web = lab.machines[1]
    assert web.build == "web" and web.image is None and not web.console
    assert [(n.net, n.addr) for n in web.nets] == [("lan", "10.0.0.20/24")]
    assert (recipe.name, recipe.version) == ("net-hello", "1")
    assert recipe.stages[0].check_node == "web"
    assert recipe.parents == () and recipe.steps == ()


@pytest.mark.tier1
def test_image_machine_and_gateway() -> None:
    lab, _ = parse_labfile(_with(
        "machine pc\n  console\n  build pc\n  net lan 10.0.0.10/24\n  gw 10.0.0.1\n"
        "machine r\n  image bunnyton/router:1\n  net lan 10.0.0.1/24\n  net wan 192.168.5.1/24\n"))
    assert lab.machines[0].gw == "10.0.0.1"
    assert lab.machines[1].image == "bunnyton/router:1"
    assert [n.net for n in lab.machines[1].nets] == ["lan", "wan"]


@pytest.mark.tier1
@pytest.mark.parametrize(("machines", "error"), [
    ("machine pc\n  build pc\n  net lan 10.0.0.10/24\n", "консол"),                              # no console
    (_PC + "machine b\n  console\n  build b\n  net lan 10.0.0.11/24\n", "консол"),               # two
    (_PC + "machine b\n  build b\n  image x:1\n  net lan 10.0.0.11/24\n", "build или image"),
    (_PC + "machine b\n  net lan 10.0.0.11/24\n", "build или image"),
    (_PC + "machine pc\n  build b\n  net lan 10.0.0.11/24\n", "повтор"),
    (_PC + "machine Web_1\n  build b\n  net lan 10.0.0.11/24\n", "имя машины"),
    (_PC + "machine b\n  build b\n  net lan 10.0.0.300/24\n", "адрес"),
    (_PC + "machine b\n  build b\n  net lan 10.0.0.11\n", "адрес"),
    (_PC + "machine b\n  build b\n  net lan 10.0.0.11/16\n", "подсет"),
    (_PC + "machine b\n  build b\n  net lan 10.1.0.11/24\n", "подсет"),
    (_PC + "machine b\n  build b\n  net lan 10.0.0.10/24\n", "занят"),
    (_PC + "machine b\n  build b\n  net lan 10.0.0.11/24\n  gw 10.9.9.9\n", "gw"),
    (_PC + "machine b\n  build b\n  net Lan! 10.0.0.11/24\n", "имя сети"),
    (_PC + "machine b\n  build b\n" + "".join(f"  net n{i} 10.{i}.0.2/24\n" for i in range(5)), "интерфейс"),
    (_PC + "".join(f"machine m{i}\n  build m\n  net lan 10.0.0.{20 + i}/24\n" for i in range(8)), "машин"),
    ("machine pc\n  console\n  build pc\n", "сет"),                                               # console offline
    (_PC + "machine b\n  build b\n  frob 1\n", "frob"),
])
def test_author_errors_are_plain_russian(machines: str, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        parse_labfile(_with(machines))


@pytest.mark.tier1
def test_check_live_on_an_unknown_machine() -> None:
    with pytest.raises(ValueError, match="db"):
        parse_labfile(_with(_PC, 'say "x"\nstage\n  solve true\n  check live on db true\n'))


@pytest.mark.tier1
def test_build_steps_belong_in_a_machine_taskfile() -> None:
    with pytest.raises(ValueError, match="Taskfile машины"):
        parse_labfile(_with(_PC, "run echo hi\n" + 'say "x"\nstage\n  solve true\n'))
    with pytest.raises(ValueError, match="Taskfile машины"):
        parse_labfile(_with(_PC, "from x:1\n" + 'say "x"\nstage\n  solve true\n'))


@pytest.mark.tier1
def test_lab_line_is_required() -> None:
    with pytest.raises(ValueError, match="lab"):
        parse_labfile(_PC + 'say "x"\nstage\n  solve true\n')
