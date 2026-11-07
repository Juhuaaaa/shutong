"""Thin command line over the Organizer: libraries, settings, scan, items, execute."""
import argparse
import json
import os
from pathlib import Path
import socket
import sys
import time
from typing import List, Optional

from shutong.engine.ai_recognize import AiNotConfigured
from shutong.engine.organizer import LibraryUnavailable, Organizer
from shutong.engine.states import ItemStatus
from shutong.engine.template import TemplateError, validate_template
from shutong.services import build_services
from shutong.store.db import Database, SchemaTooNew
from shutong.store.records import ItemStore, LibraryStore, RunStore
from shutong.store.settings import SettingsStore

# Tests replace this to inject a fake metadata source.
services_factory = build_services

EXIT_OK, EXIT_USAGE, EXIT_REVIEW, EXIT_FAILED = 0, 2, 3, 4
_DESKTOP_EXIT_SECONDS = 5


def main(argv: Optional[List[str]] = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.handler is _desktop_selftest:
        return _desktop_selftest(args)
    if args.handler is _desktop_serve:  # settles the database itself: it may have to refuse or back it up first
        return _desktop_serve(args)
    db = Database(Path(args.data).expanduser() / "shutong.db")
    db.migrate()
    try:
        return args.handler(args, db)
    except (KeyError, TemplateError, ValueError, LibraryUnavailable, AiNotConfigured, OSError) as error:
        print("错误：{0}".format(error), file=sys.stderr)
        return EXIT_USAGE


def default_web_dir() -> Path:
    """The web UI built inside a source checkout: <repo>/web/dist."""
    return Path(__file__).resolve().parents[2] / "web" / "dist"


def _serve(args, db) -> int:
    import dataclasses

    import uvicorn

    from shutong.api.app import create_app

    factory = services_factory
    if args.offline_metadata:
        from shutong.metadata.offline import OfflineSource

        path = Path(args.offline_metadata)
        if not path.is_file():
            print("错误：离线元数据文件不存在：{0}".format(path), file=sys.stderr)
            return EXIT_USAGE
        source = OfflineSource(path)
        factory = lambda database: dataclasses.replace(services_factory(database), source=source)  # noqa: E731
    web = Path(args.web) if args.web else (Path(os.environ["SHUTONG_WEB"]) if os.environ.get("SHUTONG_WEB")
                                            else default_web_dir())
    app = create_app(Path(args.data).expanduser(), services_factory=factory, web_dist=web, log_console=True)
    uvicorn.run(app, host=args.host, port=args.port)
    return EXIT_OK


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="shutong", description="书童：漫画与轻小说整理")
    parser.add_argument("--data", default=os.environ.get("SHUTONG_DATA", "~/.shutong"),
                        help="数据目录（数据库 shutong.db 放在这里）")
    commands = parser.add_subparsers(dest="command", required=True)

    library = commands.add_parser("library", help="管理库").add_subparsers(dest="action", required=True)
    add = library.add_parser("add")
    add.add_argument("name")
    add.add_argument("--kind", choices=("manga", "novel"), required=True)
    add.add_argument("--source", required=True)
    add.add_argument("--library", required=True)
    add.add_argument("--policy", choices=("keep", "archive", "delete"), default="keep")
    add.add_argument("--archive")
    add.add_argument("--template", default="")
    add.add_argument("--no-pdf-to-cbz", action="store_true")
    add.set_defaults(handler=_library_add)
    library.add_parser("list").set_defaults(handler=_library_list)
    library_set = library.add_parser("set")
    library_set.add_argument("name")
    library_set.add_argument("--template", help="命名模板；空字符串恢复默认")
    library_set.set_defaults(handler=_library_set)


    setting = commands.add_parser("setting", help="设置").add_subparsers(dest="action", required=True)
    setting_set = setting.add_parser("set")
    setting_set.add_argument("key")
    setting_set.add_argument("value")
    setting_set.set_defaults(handler=_setting_set)
    setting.add_parser("list").set_defaults(handler=_setting_list)

    scan = commands.add_parser("scan", help="扫描来源目录并生成预览")
    scan.add_argument("library")
    scan.set_defaults(handler=_scan)

    items = commands.add_parser("items", help="列出条目")
    items.add_argument("library")
    items.add_argument("--status", choices=[status.value for status in ItemStatus])
    items.set_defaults(handler=_items)

    retry = commands.add_parser("retry", help="重试：整理出错、待重试 / 卡住 / 重复的条目")
    retry.add_argument("library")
    retry.add_argument("item_ids", nargs="*", type=int)
    retry.add_argument("--all", action="store_true", help="库里所有失败、待重试、卡住的条目")
    retry.set_defaults(handler=_retry)


    serve = commands.add_parser("serve", help="启动 Web 服务（API 与界面）")
    serve.add_argument("--host", default=os.environ.get("SHUTONG_HOST", "0.0.0.0"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("SHUTONG_PORT", "8080")))
    serve.add_argument("--web", help="前端构建目录；默认取环境变量 SHUTONG_WEB，再默认仓库里的 web/dist")
    serve.add_argument("--offline-metadata", help=argparse.SUPPRESS)  # tests / demos: subjects from a JSON file
    serve.set_defaults(handler=_serve)


    desktop = commands.add_parser("desktop-serve", help=argparse.SUPPRESS)
    desktop.add_argument("--web", help="前端构建目录")
    desktop.add_argument("--port", type=int, default=0, help="想用的端口；被占用时换一个")
    desktop.set_defaults(handler=_desktop_serve)

    selftest = commands.add_parser("desktop-selftest", help=argparse.SUPPRESS)
    selftest.add_argument("archive")
    selftest.add_argument("--list", action="store_true", help="只列出文件名")
    selftest.set_defaults(handler=_desktop_selftest)

    execute = commands.add_parser("execute", help="执行已确认的预览")
    execute.add_argument("library")
    execute.add_argument("item_ids", nargs="*", type=int)
    execute.add_argument("--all-planned", action="store_true")
    execute.set_defaults(handler=_execute)
    return parser


def _desktop_listener(port: int) -> socket.socket:
    """The page's stored settings belong to its address: the same port as last time when possible."""
    listener = socket.socket()
    if os.name != "nt":  # lets it through the wait a quit leaves behind; on Windows it would let others share the port
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener.bind(("127.0.0.1", port))
    except OSError:
        listener.close()
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
    return listener


def _desktop_serve(args) -> int:
    """The backend of the desktop app. Stdout carries one line for Electron; closing stdin ends the process,
    so that a crashed window never leaves a backend behind."""
    import threading

    import uvicorn

    from shutong.api.app import create_app

    token = os.environ.get("SHUTONG_DESKTOP_TOKEN")
    if not token:
        print("错误：缺少 SHUTONG_DESKTOP_TOKEN", file=sys.stderr)
        return EXIT_USAGE
    data = Path(args.data).expanduser()
    data.mkdir(parents=True, exist_ok=True)
    db = Database(data / "shutong.db")
    try:
        db.check_compatible()
    except SchemaTooNew as error:
        print("SHUTONG_ERROR " + json.dumps({"code": "schema_too_new", "message": str(error)}, ensure_ascii=False),
              flush=True)
        return 1
    db.backup_before_upgrade()
    web = Path(args.web) if args.web else default_web_dir()
    app = create_app(data, web_dist=web, desktop_token=token)
    listener = _desktop_listener(args.port)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False, log_config=None))

    def announce() -> None:
        while not server.started and not server.should_exit:
            time.sleep(0.05)
        if server.started:
            print("SHUTONG_READY " + json.dumps({"port": port}), flush=True)

    def until_stdin_closes() -> None:
        try:
            while sys.stdin.buffer.read(4096):
                pass
        except (OSError, ValueError):
            pass
        server.should_exit = True
        # A job in the middle of a file must not hold the exit: recovery settles it at the next start.
        timer = threading.Timer(_DESKTOP_EXIT_SECONDS, os._exit, (0,))
        timer.daemon = True
        timer.start()

    threading.Thread(target=announce, daemon=True).start()
    threading.Thread(target=until_stdin_closes, daemon=True).start()
    server.run(sockets=[listener])
    # Worker threads of a stopped job would keep the interpreter alive.
    sys.stdout.flush()
    os._exit(EXIT_OK)


def _desktop_selftest(args) -> int:
    """For the packaging smoke test: can this build read an archive, with everything it needs on board?"""
    import tempfile

    import numpy  # noqa: F401
    from PIL import Image  # noqa: F401
    import pypdf  # noqa: F401

    from shutong.engine.kinds.manga.cbz import _archive_names, collect_archive_pages

    if args.list:
        print(json.dumps({"names": _archive_names(Path(args.archive))}))  # escaped: no console code page can garble it
        return EXIT_OK
    with tempfile.TemporaryDirectory() as work:
        pages = collect_archive_pages(Path(args.archive), Path(work))
    print(json.dumps({"pages": len(pages)}))
    return EXIT_OK


def _library_add(args, db) -> int:
    if args.template:
        validate_template(args.template)
    library = LibraryStore(db).create(
        args.name, args.kind, Path(args.source).expanduser(), Path(args.library).expanduser(),
        source_policy=args.policy, archive_dir=Path(args.archive).expanduser() if args.archive else None,
        naming_template=args.template, pdf_to_cbz=not args.no_pdf_to_cbz,
    )
    print("已添加库 {0}（id {1}）".format(library.name, library.id))
    return EXIT_OK


def _library_list(args, db) -> int:
    for library in LibraryStore(db).all():
        print("{0}\t{1}\t{2} → {3}\t{4}\t{5}".format(library.name, library.kind, library.source_dir,
                                                     library.library_dir, library.source_policy,
                                                     library.naming_template or "（默认模板）"))
    return EXIT_OK


def _library_set(args, db) -> int:
    store = LibraryStore(db)
    library = store.by_name(args.name)
    if args.template:
        validate_template(args.template)
    store.update(library.id, naming_template=args.template)
    print("已更新库 {0}".format(library.name))
    return EXIT_OK


def _setting_set(args, db) -> int:
    try:
        value = json.loads(args.value)
    except json.JSONDecodeError:
        value = args.value
    SettingsStore(db).set(args.key, value)
    return EXIT_OK


def _setting_list(args, db) -> int:
    for key, value in sorted(SettingsStore(db).public().items()):
        print("{0} = {1}".format(key, value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)))
    return EXIT_OK


def _organizer(db) -> Organizer:
    organizer = Organizer(services_factory(db))
    organizer.recover()
    return organizer


def _scan(args, db) -> int:
    library = LibraryStore(db).by_name(args.library)
    organizer = _organizer(db)
    run_id = organizer.scan(library.id)
    items = [item for item in ItemStore(db).list(library.id) if item.run_id == run_id]
    for item in items:
        print(_describe(library, item))
    counts = RunStore(db).counts(run_id)
    print("known {0}".format(counts.get("known", 0)))
    return _exit_code(item.status for item in items)


def _items(args, db) -> int:
    library = LibraryStore(db).by_name(args.library)
    status = ItemStatus(args.status) if args.status else None
    for item in ItemStore(db).list(library.id, status):
        print(_describe(library, item))
    return EXIT_OK


def _execute(args, db) -> int:
    library = LibraryStore(db).by_name(args.library)
    organizer = _organizer(db)
    item_ids = list(args.item_ids)
    if args.all_planned:
        store = ItemStore(db)
        item_ids += [item.id for status in (ItemStatus.PLANNED, ItemStatus.READY)
                     for item in store.list(library.id, status)]
    counts = organizer.execute(item_ids)
    print("published {published}  review {review}  failed {failed}  skipped {skipped}".format(**counts))
    if counts["failed"]:
        return EXIT_FAILED
    return EXIT_REVIEW if counts["review"] else EXIT_OK


def _retry(args, db) -> int:
    library = LibraryStore(db).by_name(args.library)
    organizer = _organizer(db)
    store = ItemStore(db)
    item_ids = [item_id for item_id in args.item_ids if store.get(item_id).library_id == library.id]
    if args.all:
        item_ids += [item.id for status in (ItemStatus.FAILED, ItemStatus.PARSED, ItemStatus.DISCOVERED,
                                            ItemStatus.MATCHED)
                     for item in store.list(library.id, status)]
    counts = organizer.retry(item_ids)
    print("ready {ready}  replanned {replanned}  skipped {skipped}".format(**counts))
    return _exit_code(store.get(item_id).status for item_id in item_ids)


def _describe(library, item) -> str:
    try:
        source = Path(item.source_path).relative_to(library.source_dir).as_posix()
    except ValueError:
        source = str(item.source_path)
    if item.status is ItemStatus.NEEDS_REVIEW:
        outcome = "复核：{0}".format(item.review_reason.value if item.review_reason else "")
    elif item.error:
        outcome = item.error
    else:
        outcome = item.target_path.as_posix() if item.target_path else ""
    return "{0:<13} {1} → {2}".format(item.status.value, source, outcome)


def _exit_code(statuses) -> int:
    statuses = set(statuses)
    if ItemStatus.FAILED in statuses:
        return EXIT_FAILED
    # PARSED means "waiting for the metadata source": it needs the user's attention too.
    return EXIT_REVIEW if statuses & {ItemStatus.NEEDS_REVIEW, ItemStatus.PARSED} else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
