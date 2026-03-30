#!/usr/bin/env python3
"""
Screenshot utility for visual verification by Claude agents.

Takes a headless browser screenshot of any URL. Agents call this via Bash,
then use the Read tool on the resulting PNG to verify UI correctness.

CUSTOMIZE: Adapt auth injection for your app (JWT, cookies, etc.).
Remove auth logic entirely if your app has no authentication or if
you only screenshot public pages.

Requires: pip install playwright && playwright install chromium
Optional: pip install Pillow (for --compare side-by-side images)

Usage:
  python scripts/screenshot.py URL [options]
  python scripts/screenshot.py --clean  # Remove all screenshots

Examples:
  python scripts/screenshot.py http://localhost:3000/ \
    --output data/screenshots/home.png

  python scripts/screenshot.py http://localhost:3000/dashboard \
    --wait-ms 3000 --output data/screenshots/dashboard.png

  python scripts/screenshot.py http://localhost:3000/settings \
    --action "click:#advanced-tab" --wait-ms 2000 \
    --output data/screenshots/settings.png

  # Mobile viewport
  python scripts/screenshot.py http://localhost:3000/ \
    --width 390 --height 844 --output data/screenshots/home_mobile.png

  # Compare against baseline
  python scripts/screenshot.py http://localhost:3000/dashboard \
    --output data/screenshots/new.png --compare data/screenshots/baseline.png
"""

import argparse
import glob
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCREENSHOTS_DIR = PROJECT_ROOT / "data" / "screenshots"


# --- AUTH INJECTION (customize for your app) ---
# Replace this with your app's auth mechanism, or remove if not needed.
# Examples:
#   - JWT in localStorage: page.evaluate("localStorage.setItem('token', '...')")
#   - Cookie: context.add_cookies([{"name": "session", "value": "...", ...}])
#   - Basic auth: browser.new_context(http_credentials={"username": "x", "password": "y"})

def inject_auth(page, url):
    """Inject authentication before navigating to the target page.

    Override this function for your app's auth mechanism.
    Return True if auth was injected, False to skip.
    """
    # Example JWT injection (uncomment and adapt):
    # parsed = urlparse(url)
    # origin = f"{parsed.scheme}://{parsed.netloc}"
    # page.goto(origin, wait_until="domcontentloaded", timeout=15000)
    # token = mint_jwt()  # Your JWT minting function
    # page.evaluate(f"localStorage.setItem('auth_token', '{token}')")
    # return True
    return False


# --- SCREENSHOT LOGIC ---

def clean_screenshots():
    """Remove all screenshots from the output directory."""
    removed = 0
    for f in glob.glob(str(SCREENSHOTS_DIR / "*.png")):
        os.remove(f)
        removed += 1
    print(f"Cleaned {removed} screenshot(s) from {SCREENSHOTS_DIR}")


def create_comparison(rendered_path: str, reference_path: str, output_path: str):
    """Create a side-by-side comparison image: reference (left) | rendered (right)."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("WARNING: Pillow not installed, skipping comparison. pip install Pillow")
        return None

    ref = Image.open(reference_path)
    rendered = Image.open(rendered_path)

    # Scale reference to match rendered height
    target_h = rendered.height
    ref_scale = target_h / ref.height
    ref_resized = ref.resize(
        (int(ref.width * ref_scale), target_h), Image.LANCZOS
    )

    # Create composite with labels
    gap = 20
    label_h = 40
    total_w = ref_resized.width + gap + rendered.width
    total_h = target_h + label_h
    composite = Image.new("RGB", (total_w, total_h), (30, 30, 30))
    draw = ImageDraw.Draw(composite)

    draw.text((ref_resized.width // 2 - 40, 8), "REFERENCE",
              fill=(255, 200, 100))
    draw.text((ref_resized.width + gap + rendered.width // 2 - 30, 8),
              "CURRENT", fill=(100, 255, 100))

    composite.paste(ref_resized, (0, label_h))
    composite.paste(rendered, (ref_resized.width + gap, label_h))

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    composite.save(output_path)
    size_kb = os.path.getsize(output_path) / 1024
    print(f"Comparison saved: {output_path} ({size_kb:.0f} KB)")
    return output_path


def take_screenshot(url, output, width, height, full_page, selector,
                    wait_for, wait_ms, actions, no_auth, device_scale):
    """Navigate to URL, optionally interact, and save a screenshot."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=device_scale,
        )
        page = context.new_page()

        # Auth injection (skip with --no-auth)
        if not no_auth:
            inject_auth(page, url)

        # Navigate to target page
        # Use 'load' (not 'networkidle') — SPAs often never reach networkidle
        # due to ongoing API calls. Rely on --wait-ms and --wait-for instead.
        page.goto(url, wait_until="load", timeout=30000)

        # Wait for a specific element if requested
        if wait_for:
            try:
                page.wait_for_selector(wait_for, timeout=15000)
            except Exception as e:
                print(f"WARNING: --wait-for '{wait_for}' timed out: {e}")

        # Execute interaction actions
        for action in actions:
            kind, _, value = action.partition(":")
            if kind == "click":
                try:
                    page.click(value, timeout=10000)
                except Exception as e:
                    print(f"WARNING: click '{value}' failed: {e}")
            elif kind == "wait":
                try:
                    page.wait_for_selector(value, timeout=15000)
                except Exception as e:
                    print(f"WARNING: wait '{value}' timed out: {e}")
            elif kind == "wait-ms":
                page.wait_for_timeout(int(value))

        # Final settle time
        if wait_ms:
            page.wait_for_timeout(wait_ms)

        # Capture screenshot
        os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)

        if selector:
            element = page.query_selector(selector)
            if element:
                element.screenshot(path=output)
            else:
                print(f"WARNING: selector '{selector}' not found, capturing viewport")
                page.screenshot(path=output, full_page=full_page)
        else:
            page.screenshot(path=output, full_page=full_page)

        browser.close()

    size_kb = os.path.getsize(output) / 1024
    print(f"Screenshot saved: {output} ({size_kb:.0f} KB)")
    return output


def main():
    parser = argparse.ArgumentParser(
        description="Screenshot utility for visual verification")
    parser.add_argument("url", nargs="?", help="URL to screenshot")
    parser.add_argument("--output", "-o", help="Output PNG path")
    parser.add_argument("--width", type=int, default=1280, help="Viewport width")
    parser.add_argument("--height", type=int, default=900, help="Viewport height")
    parser.add_argument("--full-page", action="store_true", help="Full scrollable page")
    parser.add_argument("--selector", help="Capture only this CSS selector")
    parser.add_argument("--wait-for", help="Wait for this selector before capture")
    parser.add_argument("--wait-ms", type=int, default=2000, help="Extra wait (ms)")
    parser.add_argument("--action", action="append", default=[],
                        help="Action before capture: click:SEL, wait:SEL, wait-ms:N")
    parser.add_argument("--no-auth", action="store_true", help="Skip auth injection")
    parser.add_argument("--device-scale", type=int, default=1, help="Device scale factor")
    parser.add_argument("--clean", action="store_true", help="Remove all screenshots")
    parser.add_argument("--compare", metavar="REF_IMAGE",
                        help="Create side-by-side comparison with reference image")
    args = parser.parse_args()

    if args.clean:
        clean_screenshots()
        return

    if not args.url:
        parser.error("URL is required (or use --clean)")

    # Default output path
    if not args.output:
        os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
        slug = urlparse(args.url).path.strip("/").replace("/", "_") or "root"
        args.output = str(SCREENSHOTS_DIR / f"{slug}.png")

    take_screenshot(
        url=args.url,
        output=args.output,
        width=args.width,
        height=args.height,
        full_page=args.full_page,
        selector=args.selector,
        wait_for=args.wait_for,
        wait_ms=args.wait_ms,
        actions=args.action,
        no_auth=args.no_auth,
        device_scale=args.device_scale,
    )

    # Create comparison if reference provided
    if args.compare:
        comp_output = args.output.replace(".png", "_compare.png")
        create_comparison(args.output, args.compare, comp_output)


if __name__ == "__main__":
    main()
