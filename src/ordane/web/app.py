"""The HTTP surface: seven routes, server-rendered, one event stream."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..core import catalog as catalog_module
from ..core import command
from ..core import config as config_module
from ..insight import metrics
from ..presentation import ansi, language, text
from ..record.runner import Runner, RunnerError
from ..record.store import RunStore
from . import security

HERE = Path(__file__).parent


@dataclass
class Settings:
    repo: Path
    port: int
    state_dir: Path
    history_path: Path
    events_path: Path


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="Ordane", docs_url=None, redoc_url=None, openapi_url=None)
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    templates.env.filters["ansi"] = ansi.to_html
    # The same vocabulary the desktop and the terminal read, so no front end
    # can call something `high` while another calls it a cutover.
    templates.env.filters["moment"] = text.moment
    templates.env.filters["took"] = text.took
    templates.env.globals["danger"] = language.danger_badge
    templates.env.globals["danger_note"] = language.danger_note
    templates.env.globals["measure_name"] = language.measure_name
    templates.env.globals["state_name"] = language.state_name
    templates.env.globals["config_name"] = config_module.CONFIG_NAME
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    store = RunStore(settings.state_dir)
    store.prepare()
    runner = Runner(store, settings.repo, settings.events_path)

    def load_catalog():
        cfg = config_module.load(settings.repo)
        return catalog_module.build(settings.repo, cfg), cfg

    def page(request: Request, name: str, **context):
        cfg = context.get("config")
        return templates.TemplateResponse(
            request=request,
            name=name,
            context={
                "repo": settings.repo,
                "active": runner.active(),
                "read_only": not (cfg.allow_environments if cfg else []),
                **context,
            },
        )

    @app.middleware("http")
    async def guard(request: Request, call_next):
        refusal = security.check(request.method, request.headers, settings.port)
        if refusal:
            return PlainTextResponse(f"Refused: {refusal}\n", status_code=403)
        return await call_next(request)

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        cat, cfg = load_catalog()
        runs = store.all(settings.repo)
        snapshot = metrics.snapshot(
            history_path=settings.history_path,
            events_path=settings.events_path,
            runs=runs,
            slo_specs=cfg.slos,
            scope=cfg.metric_environments,
        )
        return page(
            request,
            "dashboard.html",
            catalog=cat,
            config=cfg,
            snapshot=snapshot,
            runs=runs[:10],
        )

    @app.get("/actions", response_class=HTMLResponse)
    def actions(request: Request):
        cat, cfg = load_catalog()
        groups: dict[str, list] = {}
        for target in cat.targets:
            groups.setdefault(target.group, []).append(target)
        return page(request, "actions.html", catalog=cat, config=cfg, groups=groups)

    @app.get("/launch/{name}", response_class=HTMLResponse)
    def launch_form(request: Request, name: str):
        cat, cfg = load_catalog()
        target = cat.target(name)
        if target is None:
            return page(request, "error.html", config=cfg, message=f"unknown target {name!r}")
        choices = {
            p.name: command.choices_for(p, cat, settings.repo) for p in target.params.values()
        }
        return page(
            request,
            "launch.html",
            catalog=cat,
            config=cfg,
            target=target,
            choices=choices,
            confirm=cfg.confirm_mode(name),
        )

    @app.post("/launch/{name}")
    async def launch(request: Request, name: str):
        cat, cfg = load_catalog()
        target = cat.target(name)
        if target is None:
            return page(request, "error.html", config=cfg, message=f"unknown target {name!r}")

        form = dict(await request.form())
        submitted = {k: str(v) for k, v in form.items()}
        environment = submitted.pop("environment", "")
        dry_run = submitted.pop("dry_run", "") == "on"
        submitted.pop("confirm", None)

        try:
            environment = command.validate_environment(cat, target.fixed_environment or environment)
            params = command.validate_params(target, submitted, cat, settings.repo)
            built = command.for_target(
                target=target,
                environment=environment,
                params=params,
                config=cfg,
                dry_run=dry_run,
                catalog=cat,
            )
            active = runner.start(
                kind="target",
                name=target.name,
                environment=environment,
                params=params,
                command=built,
                labels=_labels(cfg, target.name),
            )
        except (command.ValidationError, RunnerError) as exc:
            choices = {
                p.name: command.choices_for(p, cat, settings.repo) for p in target.params.values()
            }
            return page(
                request,
                "launch.html",
                catalog=cat,
                config=cfg,
                target=target,
                choices=choices,
                confirm=cfg.confirm_mode(name),
                error=str(exc),
                submitted=submitted | {"environment": environment},
            )
        return RedirectResponse(f"/runs/{active.id}", status_code=303)

    @app.get("/playbooks", response_class=HTMLResponse)
    def playbooks(request: Request):
        cat, cfg = load_catalog()
        return page(request, "playbooks.html", catalog=cat, config=cfg)

    @app.post("/playbooks")
    async def run_playbook(
        request: Request,
        playbook: str = Form(...),
        environment: str = Form(...),
        check: str = Form(""),
        diff: str = Form(""),
        limit: str = Form(""),
        tags: str = Form(""),
        skip_tags: str = Form(""),
        verbosity: int = Form(0),
    ):
        cat, cfg = load_catalog()
        try:
            environment = command.validate_environment(cat, environment)
            if cat.playbook(playbook) is None:
                raise command.ValidationError(f"unknown playbook {playbook!r}")
            built = command.for_playbook(
                playbook=playbook,
                environment=environment,
                template=cfg.playbook_command,
                flags={"check": check == "on", "diff": diff == "on"},
                limit=limit,
                tags=tags,
                skip_tags=skip_tags,
                verbosity=verbosity,
            )
            wrapped = command.Command.build(
                ["env", command.environment_assignment(cfg, environment), *built.argv]
            )
            active = runner.start(
                kind="playbook",
                name=playbook,
                environment=environment,
                params={"check": str(check == "on"), "limit": limit, "tags": tags},
                command=wrapped,
            )
        except (command.ValidationError, RunnerError) as exc:
            return page(request, "playbooks.html", catalog=cat, config=cfg, error=str(exc))
        return RedirectResponse(f"/runs/{active.id}", status_code=303)

    @app.get("/runs", response_class=HTMLResponse)
    def history(request: Request):
        _, cfg = load_catalog()
        return page(request, "history.html", config=cfg, runs=store.all(settings.repo))

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def run_detail(request: Request, run_id: str):
        _, cfg = load_catalog()
        live = runner.get(run_id)
        record = live.run if live is not None else store.get(run_id)
        if record is None:
            return page(request, "error.html", config=cfg, message=f"unknown run {run_id!r}")
        output = live.buffered() if live is not None else store.output(run_id)
        return page(
            request, "run.html", config=cfg, run=record, output=output, live=live is not None
        )

    @app.get("/runs/{run_id}/stream")
    def stream(run_id: str):
        live = runner.get(run_id)
        if live is None:
            return PlainTextResponse("no such active run\n", status_code=404)

        async def events():
            loop = asyncio.get_running_loop()
            iterator = live.stream()
            while True:
                chunk = await loop.run_in_executor(None, lambda: next(iterator, None))
                if chunk is None:
                    yield f"event: end\ndata: {live.run.state}\n\n"
                    return
                if chunk:
                    for line in chunk.splitlines():
                        yield f"data: {line}\n\n"
                else:
                    yield ": keep-alive\n\n"

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.post("/runs/{run_id}/cancel")
    def cancel(run_id: str):
        live = runner.get(run_id)
        if live is not None:
            live.cancel()
        return RedirectResponse(f"/runs/{run_id}", status_code=303)

    @app.get("/environments", response_class=HTMLResponse)
    def environments(request: Request):
        cat, cfg = load_catalog()
        return page(request, "environments.html", catalog=cat, config=cfg)

    return app


def _labels(cfg: config_module.Config, target: str) -> dict[str, str]:
    """Marks the runs the metrics need to recognise later."""
    spec = cfg.targets.get(target, {}) or {}
    labels = {}
    if spec.get("deploy"):
        labels["deploy"] = "true"
    if spec.get("cutover"):
        labels["cutover"] = "true"
    return labels
