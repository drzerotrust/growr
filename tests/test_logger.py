"""Console flow, stream separation, and batch log-volume regressions."""

import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

import growr
from growr_cli.logger import (
    configure_console_logging,
    get_logger,
    suppress_console_logs,
)
from growr_cli.models import ScanReport
from tests.test_enrichment import (
    MINT,
    OTHER,
    enricher,
    launch_report,
    providers_for,
)
from tests.test_stonks import cli_dependencies


@pytest.fixture(autouse=True)
def restore_application_logging():
    root = logging.getLogger("growr_cli")
    handlers = root.handlers[:]
    level = root.level
    propagate = root.propagate
    yield
    for handler in root.handlers[:]:
        if handler not in handlers:
            root.removeHandler(handler)
            handler.close()
    root.handlers = handlers
    root.setLevel(level)
    root.propagate = propagate


def test_console_shows_elapsed_time_on_stderr(monkeypatch, capsys):
    clock = Mock(side_effect=[10.0, 12.5])
    monkeypatch.setattr("growr_cli.logger.perf_counter", clock)
    configure_console_logging(enabled=True, use_color=False)

    get_logger("flow").info("Fetched %d pools", 30)

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "[+   2.50s] INFO Fetched 30 pools\n"


@pytest.mark.parametrize("use_color", [False, True])
@pytest.mark.parametrize("is_tty", [False, True])
def test_console_color_requires_permission_and_tty(
    monkeypatch, capsys, use_color, is_tty
):
    monkeypatch.setattr("sys.stderr.isatty", lambda: is_tty)
    configure_console_logging(enabled=True, use_color=use_color)

    get_logger("flow").warning("Partial coverage")

    assert ("\x1b[" in capsys.readouterr().err) == (use_color and is_tty)


def test_reconfiguration_preserves_other_handlers_without_duplicates(capsys):
    output = io.StringIO()
    root = logging.getLogger("growr_cli")
    root.addHandler(logging.StreamHandler(output))
    configure_console_logging(enabled=True)
    configure_console_logging(enabled=True)

    get_logger("flow").info("One event")

    assert capsys.readouterr().err.count("One event") == 1
    assert output.getvalue().count("One event") == 1


def test_default_disables_console_after_a_verbose_run(capsys):
    configure_console_logging(enabled=True)
    logger = get_logger("flow")
    logger.info("Visible verbose progress")
    assert "Visible verbose progress" in capsys.readouterr().err

    configure_console_logging()
    logger.info("Hidden progress")
    logger.warning("Hidden warning")
    logger.error("Hidden error")
    output = capsys.readouterr()
    assert output.out == output.err == ""


def test_quiet_keeps_warnings_and_errors(capsys):
    configure_console_logging(enabled=True, quiet=True)
    logger = get_logger("flow")

    logger.debug("Debug detail")
    logger.info("Progress")
    logger.warning("Partial coverage")
    logger.error("Scan failed")

    output = capsys.readouterr().err
    assert "Debug detail" not in output
    assert "Progress" not in output
    assert "Partial coverage" in output
    assert "Scan failed" in output


def test_suppression_is_worker_local_and_restored_after_failure(capsys):
    configure_console_logging(enabled=True)
    logger = get_logger("flow")

    def worker():
        with pytest.raises(ValueError), suppress_console_logs():
            logger.info("Hidden worker details")
            raise ValueError("worker failed")
        logger.info("Worker logging restored")

    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(worker).result()
    logger.info("Main thread remains visible")

    output = capsys.readouterr().err
    assert "Hidden worker details" not in output
    assert "Worker logging restored" in output
    assert "Main thread remains visible" in output


@pytest.mark.parametrize("pool_count", [1, 60])
def test_enrichment_summarizes_batches_without_per_pool_logs(
    capsys, pool_count
):
    configure_console_logging(enabled=True, use_color=False)
    mints = [MINT, OTHER] if pool_count > 1 else [MINT]
    launches = [
        {"mint": mints[index % len(mints)], "pool": f"pool-{index}"}
        for index in range(pool_count)
    ]

    def scan(mint):
        get_logger("scan").info("Individual scan details")
        if mint == OTHER:
            raise ValueError("secret RPC endpoint")
        return ScanReport("token", mint, "mock RPC", "now")

    enricher(providers_for(mints), scan).enrich(launch_report(launches))

    output = capsys.readouterr().err
    assert len(output.splitlines()) == 8
    assert output.count("RPC coverage:") == 1
    assert "Individual scan details" not in output
    assert "secret" not in output
    assert MINT not in output
    if pool_count > 1:
        assert "WARNING RPC coverage: failed=1, success=1" in output


@pytest.mark.parametrize("quiet", [False, True])
def test_cli_progress_keeps_json_parseable(monkeypatch, capsys, quiet):
    flags = ["--quiet"] if quiet else ["--verbose"]
    cli_dependencies(monkeypatch, [*flags, "--json", "list", "--stonk"])

    assert growr.main() == 0

    output = capsys.readouterr()
    assert json.loads(output.out)["request"]["options"]["mode"] == "recent"
    assert ("Run complete" in output.err) == (not quiet)
    if quiet:
        assert output.err == ""


def test_quiet_failure_still_reports_error_without_completion(
    monkeypatch, capsys
):
    cli_dependencies(monkeypatch, ["--quiet", "--json", "list", "--stonk"])
    growr.StonksSearcher.return_value.search.side_effect = ValueError(
        "Stonks returned HTTP 503"
    )

    assert growr.main() == 1

    output = capsys.readouterr()
    assert json.loads(output.out)["error"]["code"] == "EXECUTION_FAILED"
    assert "ERROR Scan failed" in output.err
    assert "Run complete" not in output.err
