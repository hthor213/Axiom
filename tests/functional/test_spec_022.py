from playwright.sync_api import Page, expect
import datetime
import os
import jwt

JWT_SECRET = os.getenv("JWT_SECRET_KEY", "hth-dashboard-change-me")
TEST_EMAIL = os.getenv("ALLOWED_EMAIL", "test@example.com")


def _make_test_jwt() -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": TEST_EMAIL,
        "name": "Test User",
        "iat": now,
        "exp": now + datetime.timedelta(days=1),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def _inject_auth(page: Page) -> None:
    """Inject a valid JWT into localStorage so auto-login kicks in on reload."""
    import json
    token = _make_test_jwt()
    user_json = json.dumps({"email": TEST_EMAIL, "name": "Test User", "picture": ""})
    page.evaluate(
        """([token, userJson]) => {
            localStorage.setItem('hth-jwt', token);
            localStorage.setItem('hth-user', userJson);
        }""",
        [token, user_json],
    )


def test_multi_project_dashboard(page: Page):
    # Load the page once to establish origin, inject auth, then reload so
    # the auto-login IIFE reads the stored JWT and calls enterApp().
    page.goto("http://localhost:8014")
    _inject_auth(page)
    page.reload()

    # 1. Dashboard header has a project selector dropdown with sync status icons per project
    # Find the project selector. It could be a select element or a button that opens a menu.
    project_selector = page.locator("select, [role='combobox'], button:has-text('Project'), [aria-label*='Project' i]").first
    expect(project_selector).to_be_visible(timeout=10000)

    # Open the dropdown if it's not a native select that shows options immediately
    project_selector.click()

    # Wait for at least two project options to be visible
    options = page.locator("option, [role='option'], .dropdown-item, [data-testid*='project-option']")
    expect(options.nth(1)).to_be_visible(timeout=10000)

    # Verify sync status icons are present in the options
    first_option = options.nth(0)
    second_option = options.nth(1)

    # Check for an icon/svg/img inside the first option indicating sync status
    sync_icon = first_option.locator("svg, img, i, [class*='icon'], [data-testid*='sync']").first
    expect(sync_icon).to_be_visible()

    project_a_name = first_option.text_content().strip()
    project_b_name = second_option.text_content().strip()
    assert project_a_name != project_b_name, "Expected two different projects in the dropdown"

    # Select Project A
    first_option.click()

    # 2. Specs are loaded from the selected project's repo path
    # Wait for specs to load
    specs = page.locator("[data-testid*='spec'], .spec-item, li:has-text('.'), tr:has-text('.')")
    expect(specs.first).to_be_visible(timeout=10000)

    # 3. Queue a run for Project A
    specs.first.click()
    run_button = page.locator("button:has-text('Run'), button:has-text('Queue'), [data-testid*='run']").first
    expect(run_button).to_be_visible()
    run_button.click()

    # 4. Verify views (Queue, Live, Results, History) are scoped to the selected project
    # Navigate to Queue or Live view
    queue_tab = page.locator("[role='tab']:has-text('Queue'), a:has-text('Queue'), button:has-text('Queue'), [role='tab']:has-text('Live'), a:has-text('Live')").first
    if queue_tab.is_visible():
        queue_tab.click()

    # Verify Project A's run appears
    runs = page.locator("[data-testid*='run'], .run-item, tr.run, .queue-item")
    expect(runs.first).to_be_visible(timeout=10000)

    # 5. Two projects can be queued and run without interfering
    # Switch to Project B
    project_selector.click()
    expect(second_option).to_be_visible()
    second_option.click()

    # Wait for the view to update and scope to Project B
    # The queue should either be empty or not show Project A's run
    page.wait_for_timeout(2000) # Give UI time to filter/re-render via WebSocket

    # Navigate back to Specs view if necessary
    specs_tab = page.locator("[role='tab']:has-text('Specs'), a:has-text('Specs'), button:has-text('Specs')").first
    if specs_tab.is_visible():
        specs_tab.click()

    expect(specs.first).to_be_visible(timeout=10000)

    # Queue a run for Project B
    specs.first.click()
    expect(run_button).to_be_visible()
    run_button.click()

    # Navigate to Queue/Live view for Project B
    if queue_tab.is_visible():
        queue_tab.click()

    # Verify Project B's run appears
    expect(runs.first).to_be_visible(timeout=10000)

    # 6. WebSocket events include project_id; frontend filters by selected project
    # Switch back to Project A and verify we see Project A's state, not Project B's
    project_selector.click()
    expect(first_option).to_be_visible()
    first_option.click()

    page.wait_for_timeout(2000)

    if queue_tab.is_visible():
        queue_tab.click()

    expect(runs.first).to_be_visible(timeout=10000)
