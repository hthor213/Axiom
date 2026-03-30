"""Chain command — walk the runtime pipeline step by step.

Each subcommand executes one link in the chain, reading input from
the database and writing output back. This makes every intermediate
value inspectable and every failure locatable.

Chain: enqueue → claim → worktree → agent → diff → adversarial → gate
"""

import json
import os
import subprocess
import sys

import click


def _get_store(ctx):
    """Get a TaskStore from the CLI context."""
    platform_root = ctx.obj.get("platform_root", os.getcwd())
    lib_path = os.path.join(platform_root, "lib", "python")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)

    from runtime.db import TaskStore

    pg_url = os.environ.get("DATABASE_URL")
    return TaskStore(
        db_path=os.path.join(platform_root, "dashboard.db"),
        pg_conn_string=pg_url,
    )


def _get_repo_root(ctx):
    return ctx.obj.get("platform_root", os.getcwd())


@click.group()
@click.pass_context
def chain(ctx):
    """Walk the runtime pipeline step by step.

    Each subcommand is one link in the chain. Output is saved to
    the database between steps so you can inspect and debug.
    """
    pass


@chain.command()
@click.option("--spec", required=True, help="Spec number (e.g. 015)")
@click.option("--title", default="", help="Spec title")
@click.option("--item", default="__draft_review__", help="Done When item or __draft_review__")
@click.option("--instructions", default="", help="User instructions for the agent")
@click.pass_context
def enqueue(ctx, spec, title, item, instructions):
    """Step 1: Create a task in the queue."""
    store = _get_store(ctx)

    from runtime.db import Task
    task = store.enqueue_task(Task(
        spec_number=spec,
        spec_title=title or f"Spec {spec}",
        done_when_item=item,
        queued_by="chain",
        user_instructions=instructions,
    ))

    click.echo(f"  task_id:  {task.id}")
    click.echo(f"  spec:     {task.spec_number}")
    click.echo(f"  item:     {task.done_when_item}")
    click.echo(f"  status:   {task.status}")
    click.echo(f"\nNext: hth-platform chain claim --task-id {task.id}")


@chain.command()
@click.option("--task-id", type=int, default=None, help="Claim a specific task (default: next in queue)")
@click.pass_context
def claim(ctx, task_id):
    """Step 2: Claim a task from the queue (sets status=running)."""
    store = _get_store(ctx)

    if task_id:
        task = store.get_task(task_id)
        if not task:
            click.echo(f"  ERROR: Task {task_id} not found")
            return
        if task.status != "queued":
            click.echo(f"  ERROR: Task {task_id} status is '{task.status}', expected 'queued'")
            return
        store.update_task_status(task_id, "running")
        task.status = "running"
    else:
        task = store.claim_next_task()
        if not task:
            click.echo("  ERROR: No queued tasks")
            return

    click.echo(f"  task_id:  {task.id}")
    click.echo(f"  spec:     {task.spec_number} — {task.spec_title}")
    click.echo(f"  item:     {task.done_when_item}")
    click.echo(f"  status:   {task.status}")
    click.echo(f"\nNext: hth-platform chain worktree --task-id {task.id}")


@chain.command()
@click.option("--task-id", type=int, required=True)
@click.option("--base-branch", default=None, help="Base branch (default: current branch)")
@click.pass_context
def worktree(ctx, task_id, base_branch):
    """Step 3: Create a git worktree for the task."""
    store = _get_store(ctx)
    repo_root = _get_repo_root(ctx)

    task = store.get_task(task_id)
    if not task:
        click.echo(f"  ERROR: Task {task_id} not found")
        return

    lib_path = os.path.join(repo_root, "lib", "python")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)

    from runtime.worktree import create_worktree

    # Default to current branch if not specified
    if not base_branch:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, cwd=repo_root,
        )
        base_branch = result.stdout.strip() if result.returncode == 0 else "main"

    wt = create_worktree(
        repo_root=repo_root,
        task_id=task_id,
        spec_number=task.spec_number,
        base_branch=base_branch,
        worktree_dir="/tmp/hth-worktrees",
    )

    # Store worktree info on the task row
    store.update_task_status(
        task_id, task.status,
        branch_name=wt.branch,
        worktree_path=wt.path,
        base_commit=wt.base_commit,
    )

    click.echo(f"  task_id:      {task_id}")
    click.echo(f"  worktree:     {wt.path}")
    click.echo(f"  branch:       {wt.branch}")
    click.echo(f"  base_branch:  {wt.base_branch}")
    click.echo(f"  base_commit:  {wt.base_commit}")
    click.echo(f"  stored in DB: task.worktree_path, task.branch_name, task.base_commit")
    click.echo(f"\nNext: hth-platform chain agent --task-id {task_id}")


@chain.command()
@click.option("--task-id", type=int, required=True)
@click.option("--fake", is_flag=True, help="Write a test change instead of running Claude")
@click.pass_context
def agent(ctx, task_id, fake):
    """Step 4: Run agent in worktree (or --fake to simulate)."""
    store = _get_store(ctx)
    repo_root = _get_repo_root(ctx)

    task = store.get_task(task_id)
    if not task:
        click.echo(f"  ERROR: Task {task_id} not found")
        return
    if not task.worktree_path:
        click.echo(f"  ERROR: Task {task_id} has no worktree_path — run 'chain worktree' first")
        return

    if fake:
        # Simulate agent: modify a file in the worktree
        spec_dir = os.path.join(task.worktree_path, "specs")
        target = None
        if os.path.isdir(spec_dir):
            for fname in os.listdir(spec_dir):
                if fname.startswith(f"{task.spec_number}-") and fname.endswith(".md"):
                    target = os.path.join(spec_dir, fname)
                    break

        if not target:
            # Create a test file
            target = os.path.join(task.worktree_path, f"test_chain_{task_id}.py")
            with open(target, "w") as f:
                f.write(f"# Test file created by chain agent --fake (task {task_id})\n")
            click.echo(f"  created: {target}")
        else:
            with open(target, "a") as f:
                f.write(f"\n<!-- chain test: task {task_id} -->\n")
            click.echo(f"  modified: {target}")

        # Commit
        lib_path = os.path.join(repo_root, "lib", "python")
        if lib_path not in sys.path:
            sys.path.insert(0, lib_path)

        from runtime.worktree import commit_in_worktree
        sha = commit_in_worktree(task.worktree_path, f"chain test: task {task_id}")

        click.echo(f"  commit:   {sha}")
        click.echo(f"  mode:     fake (no Claude)")
    else:
        click.echo(f"  Running Claude in {task.worktree_path}...")
        click.echo(f"  (not implemented yet — use --fake for testing)")
        return

    click.echo(f"\nNext: hth-platform chain diff --task-id {task_id}")


@chain.command()
@click.option("--task-id", type=int, required=True)
@click.option("--ext", default=".py", help="File extension filter (e.g. .md, .py)")
@click.pass_context
def diff(ctx, task_id, ext):
    """Step 5: Show what changed in the worktree vs base."""
    store = _get_store(ctx)
    task = store.get_task(task_id)
    if not task:
        click.echo(f"  ERROR: Task {task_id} not found")
        return
    if not task.worktree_path:
        click.echo(f"  ERROR: No worktree_path on task {task_id}")
        return

    base_ref = task.base_commit or "main"
    click.echo(f"  worktree:    {task.worktree_path}")
    click.echo(f"  base_commit: {task.base_commit or '(NOT SET — using main)'}")
    click.echo(f"  diff cmd:    git diff --name-only {base_ref}...HEAD")

    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        capture_output=True, text=True,
        cwd=task.worktree_path,
    )

    click.echo(f"  returncode:  {result.returncode}")
    if result.stderr.strip():
        click.echo(f"  stderr:      {result.stderr.strip()}")

    if result.returncode != 0 or not result.stdout.strip():
        click.echo(f"  changed:     (none)")
        click.echo(f"\n  ** This is where SKIP happens — no files to review **")
        return

    all_files = result.stdout.strip().split("\n")
    filtered = [f for f in all_files if f.endswith(ext)]

    click.echo(f"  all changed: {all_files}")
    click.echo(f"  filtered ({ext}): {filtered}")

    if not filtered:
        click.echo(f"\n  ** SKIP: changed files exist but none match '{ext}' **")
    else:
        click.echo(f"\nNext: hth-platform chain adversarial --task-id {task_id} --ext {ext}")


@chain.command()
@click.option("--task-id", type=int, required=True)
@click.option("--ext", default=".py", help="File extension filter")
@click.pass_context
def adversarial(ctx, task_id, ext):
    """Step 6: Run adversarial review on changed files."""
    store = _get_store(ctx)
    repo_root = _get_repo_root(ctx)
    task = store.get_task(task_id)
    if not task:
        click.echo(f"  ERROR: Task {task_id} not found")
        return
    if not task.worktree_path:
        click.echo(f"  ERROR: No worktree_path on task {task_id}")
        return

    lib_path = os.path.join(repo_root, "lib", "python")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)

    # Step 1: Get changed files
    base_ref = task.base_commit or "main"
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        capture_output=True, text=True,
        cwd=task.worktree_path,
    )
    if result.returncode != 0 or not result.stdout.strip():
        click.echo(f"  diff returned nothing — verdict: SKIP")
        return

    changed = [f for f in result.stdout.strip().split("\n") if f.endswith(ext)]
    if not changed:
        click.echo(f"  no {ext} files in diff — verdict: SKIP")
        return

    click.echo(f"  files to review: {changed}")

    # Step 2: Load credentials
    click.echo(f"  loading credentials...")
    try:
        from adversarial.credentials import load_credentials
        creds = load_credentials(repo_root)
        click.echo(f"  credentials: {list(creds.keys())}")
    except Exception as e:
        click.echo(f"  ERROR loading credentials: {e}")
        return

    # Step 3: Resolve models
    click.echo(f"  resolving models...")
    try:
        from adversarial.model_resolver import resolve_models
        models = resolve_models(creds)
        click.echo(f"  models: {models}")
    except Exception as e:
        click.echo(f"  ERROR resolving models: {e}")
        return

    # Step 4: Run pipeline
    click.echo(f"  running adversarial pipeline...")
    try:
        from adversarial.adversarial import run_pipeline
        abs_files = [os.path.join(task.worktree_path, f) for f in changed]
        report = run_pipeline(abs_files, task.worktree_path, creds, models)
        verdict = report.get("verdict", "SKIP")
        click.echo(f"  verdict:     {verdict}")
        click.echo(f"  report keys: {list(report.keys())}")
        if "issues" in report:
            click.echo(f"  issues:      {len(report['issues'])}")
    except Exception as e:
        click.echo(f"  ERROR in pipeline: {e}")
        import traceback
        traceback.print_exc()
        return

    click.echo(f"\nNext: hth-platform chain gate --task-id {task_id}")


@chain.command()
@click.option("--task-id", type=int, required=True)
@click.pass_context
def gate(ctx, task_id):
    """Step 7: Apply quality gates (same logic as server.py)."""
    store = _get_store(ctx)
    task = store.get_task(task_id)
    if not task:
        click.echo(f"  ERROR: Task {task_id} not found")
        return

    # Check for existing result
    lib_path = os.path.join(_get_repo_root(ctx), "lib", "python")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)

    # For now, show what the gate logic WOULD do based on current data
    is_draft = task.done_when_item == "__draft_review__"
    click.echo(f"  task_id:       {task_id}")
    click.echo(f"  is_draft:      {is_draft}")
    click.echo(f"  status:        {task.status}")
    click.echo()
    click.echo(f"  Quality gate logic (from server.py:356-376):")
    click.echo(f"    tests_ran       = test_passed > 0 or test_failed > 0")
    click.echo(f"    tests_ok        = test_failed == 0 and (tests_ran or is_draft_review)")
    click.echo(f"    adversarial_ok  = adversarial_verdict == 'PASS'")
    click.echo(f"    task_passed     = tests_ok and harness_ok and (adversarial_ok or is_draft)")
    click.echo()
    click.echo(f"  For draft reviews: tests_ok=True (exempt), adversarial_ok doesn't matter")
    click.echo(f"  For code tasks:    need tests_ran=True AND adversarial_verdict='PASS'")


@chain.command("status")
@click.option("--task-id", type=int, required=True)
@click.pass_context
def status(ctx, task_id):
    """Show full state of a task across all DB tables."""
    store = _get_store(ctx)

    task = store.get_task(task_id)
    if not task:
        click.echo(f"  ERROR: Task {task_id} not found")
        return

    click.echo(f"=== Task {task_id} ===")
    click.echo(f"  spec:          {task.spec_number} — {task.spec_title}")
    click.echo(f"  item:          {task.done_when_item}")
    click.echo(f"  status:        {task.status}")
    click.echo(f"  branch:        {task.branch_name or '(none)'}")
    click.echo(f"  worktree:      {task.worktree_path or '(none)'}")
    click.echo(f"  base_commit:   {task.base_commit or '(NOT SET)'}")
    click.echo(f"  queued_by:     {task.queued_by}")
    click.echo(f"  created:       {task.created_at}")
    click.echo(f"  updated:       {task.updated_at}")

    # Check for session
    lib_path = os.path.join(_get_repo_root(ctx), "lib", "python")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)

    # Check for result
    try:
        results = store.get_results(task_id=task_id)
        for r in results:
            click.echo(f"\n=== Result {r.id} ===")
            click.echo(f"  verdict:       {r.adversarial_verdict}")
            click.echo(f"  tests:         {r.test_passed} passed, {r.test_failed} failed")
            click.echo(f"  commit:        {r.commit_sha or '(none)'}")
            click.echo(f"  approved:      {r.approved}")
            if r.adversarial_report:
                report = r.adversarial_report
                if isinstance(report, str):
                    try:
                        report = json.loads(report)
                    except Exception:
                        pass
                if isinstance(report, dict) and "error" in report:
                    click.echo(f"  report error:  {report['error']}")
    except Exception:
        pass


@chain.command("run-all")
@click.option("--spec", required=True, help="Spec number")
@click.option("--title", default="", help="Spec title")
@click.option("--item", default="__draft_review__", help="Done When item")
@click.option("--fake", is_flag=True, help="Use fake agent instead of Claude")
@click.option("--ext", default=".md", help="File extension for adversarial review")
@click.pass_context
def run_all(ctx, spec, title, item, fake, ext):
    """Run the full chain: enqueue → claim → worktree → agent → diff → adversarial."""
    click.echo("=== Chain: enqueue ===")
    # Enqueue directly so we can capture the returned task ID reliably,
    # even when other tasks are already in the queue.
    store = _get_store(ctx)
    lib_path = os.path.join(_get_repo_root(ctx), "lib", "python")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)
    from runtime.db import Task as _Task
    _task = store.enqueue_task(_Task(
        spec_number=spec,
        spec_title=title or f"Spec {spec}",
        done_when_item=item,
        queued_by="chain",
    ))
    tid = _task.id
    click.echo(f"  task_id:  {tid}")
    click.echo(f"  spec:     {_task.spec_number}")
    click.echo(f"  item:     {_task.done_when_item}")
    click.echo(f"  status:   {_task.status}")

    click.echo(f"\n=== Chain: claim (task {tid}) ===")
    ctx.invoke(claim, task_id=tid)

    click.echo(f"\n=== Chain: worktree (task {tid}) ===")
    ctx.invoke(worktree, task_id=tid, base_branch=None)

    click.echo(f"\n=== Chain: agent (task {tid}) ===")
    ctx.invoke(agent, task_id=tid, fake=fake)

    click.echo(f"\n=== Chain: diff (task {tid}) ===")
    ctx.invoke(diff, task_id=tid, ext=ext)

    click.echo(f"\n=== Chain: adversarial (task {tid}) ===")
    ctx.invoke(adversarial, task_id=tid, ext=ext)

    click.echo(f"\n=== Chain: gate (task {tid}) ===")
    ctx.invoke(gate, task_id=tid)

    click.echo(f"\n=== Chain: status (task {tid}) ===")
    ctx.invoke(status, task_id=tid)
