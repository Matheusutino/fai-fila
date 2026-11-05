"""Verifica upload, reset ao recarregar e consulta manual; exige stack e base carregadas."""

import argparse

from playwright.sync_api import sync_playwright

from app.config import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--chrome", default=None, help="Caminho opcional do Chrome instalado.")
    args = parser.parse_args()
    output = ROOT / "artifacts"
    output.mkdir(exist_ok=True)
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=args.chrome)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route(
            "**/api/reference-receipts",
            lambda route: route.fulfill(status=503, json={"detail": "Indisponível"}),
        )
        response = page.goto(args.base_url)
        assert response.headers["cache-control"] == "no-store"
        assert "?v=" in page.locator("script[src]").get_attribute("src")
        page.locator(".reference-library summary").click()
        page.get_by_role("button", name="Tentar novamente", exact=True).wait_for()
        page.unroute("**/api/reference-receipts")
        page.get_by_role("button", name="Tentar novamente", exact=True).click()
        page.locator("#reference-list button").first.click()
        page.locator("#document-viewer[open]").wait_for()
        assert page.locator("#document-content iframe").get_attribute("src").endswith("/file")
        original = page.request.get(page.locator("#open-document").evaluate("link => link.href"))
        assert original.ok and original.body().startswith(b"%PDF-")
        page.locator("#close-document").click()
        page.locator("#file").set_input_files(ROOT / "fixtures/queries/demo-001-copia.pdf")
        page.locator("#view-selected").click()
        assert page.locator("#document-content iframe").get_attribute("src").startswith("blob:")
        page.keyboard.press("Escape")
        page.get_by_role("button", name="Verificar duplicidade").click()
        page.locator("#result").wait_for(state="visible", timeout=600_000)
        assert "Possível duplicidade" in page.locator("#result").inner_text()
        token = page.locator("#current-token").text_content()
        assert token
        # Valores salvos pela versão anterior também não podem retomar a análise.
        page.evaluate("token => localStorage.setItem('fai-receipt-token', token)", token)
        automatic_queries = []
        page.on(
            "request",
            lambda request: automatic_queries.append(request.url)
            if request.url.endswith("/api/receipt-checks/" + token)
            else None,
        )
        page.reload()
        page.locator("#reference-list button").first.wait_for(state="attached")
        assert page.locator("#result").is_hidden()
        assert page.locator("#tracking").is_hidden()
        assert page.locator("#empty").is_visible()
        assert page.locator("#token-input").input_value() == ""
        assert page.locator("#file").input_value() == ""
        assert page.locator("#submit").is_disabled()
        assert automatic_queries == []
        page.locator("#token-input").fill(token)
        page.locator("#resume").click()
        page.locator("#result").wait_for(state="visible", timeout=30_000)
        assert page.locator("#current-token").text_content() == token
        page.locator("#view-uploaded").click()
        uploaded = page.request.get(page.locator("#open-document").evaluate("link => link.href"))
        assert uploaded.ok
        assert uploaded.body() == (ROOT / "fixtures/queries/demo-001-copia.pdf").read_bytes()
        page.locator("#close-document").click()
        page.get_by_role("button", name="Visualizar PDF original", exact=True).first.click()
        assert page.locator("#document-title").inner_text().endswith(".pdf")
        # O leitor nativo carrega em outra extensão/processo depois do iframe.
        page.wait_for_timeout(2000)
        page.screenshot(path=str(output / "pdf-viewer-desktop.png"))
        page.locator("#close-document").click()
        page.screenshot(path=str(output / "desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(output / "mobile.png"), full_page=True)
        page.get_by_role("button", name="Visualizar PDF original", exact=True).first.click()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.wait_for_timeout(2000)
        page.screenshot(path=str(output / "pdf-viewer-mobile.png"))
        page.keyboard.press("Escape")
        page.locator("#file").set_input_files(ROOT / "fixtures/queries/demo-001-imagem.png")
        page.locator("#view-selected").click()
        assert page.locator("#document-content img").get_attribute("src").startswith("blob:")
        page.locator("#document-content img").evaluate("img => img.decode()")
        restricted = browser.new_page()
        restricted.on("pageerror", lambda error: errors.append(str(error)))
        restricted.add_init_script(
            """for (const method of ['getItem', 'setItem']) {
              Storage.prototype[method] = () => { throw new DOMException('Blocked', 'SecurityError'); };
            }"""
        )
        restricted.goto(args.base_url)
        restricted.locator(".reference-library summary").click()
        restricted.locator("#reference-list button").first.wait_for(state="visible")
        restricted.close()
        assert not errors, errors
        browser.close()
    print(
        "Upload, reset ao recarregar, consulta manual, PDFs e layout mobile passaram; capturas em artifacts/."
    )


if __name__ == "__main__":
    main()
