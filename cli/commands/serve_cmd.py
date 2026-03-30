"""Dashboard serve command — runs the FastAPI dashboard."""

import os
import sys
import click


@click.command("serve")
@click.option("--host", default="0.0.0.0", help="Host to bind to")
@click.option("--port", default=8014, help="Port to listen on")
@click.option("--reload", is_flag=True, help="Enable auto-reload for development")
@click.pass_context
def serve(ctx, host, port, reload):
    """Start the dashboard web server."""
    # Ensure lib and repo root are on path
    platform_root = ctx.obj.get("platform_root", os.getcwd())
    lib_path = os.path.join(platform_root, "lib", "python")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)
    # dashboard/ is at repo root, not inside lib/python/
    if platform_root not in sys.path:
        sys.path.insert(0, platform_root)

    # Set repo root for the API
    os.environ.setdefault("REPO_ROOT", platform_root)

    try:
        import uvicorn
    except ImportError:
        click.echo("uvicorn required. Install with: pip install uvicorn[standard]")
        sys.exit(1)

    click.echo(f"Starting dashboard on http://{host}:{port}")
    click.echo(f"Repo root: {platform_root}")

    uvicorn.run(
        "dashboard.api.app:app",
        host=host,
        port=port,
        reload=reload,
    )
