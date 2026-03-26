const fs = require("fs");
const path = require("path");
const { pathToFileURL } = require("url");

async function main() {
  const [
    puppeteerRoot,
    mermaidHtmlPath,
    inputPath,
    outputPath,
    backgroundColor = "white",
    widthArg = "1400",
  ] = process.argv.slice(2);

  if (!puppeteerRoot || !mermaidHtmlPath || !inputPath || !outputPath) {
    throw new Error("Usage: node mermaid_renderer_fallback.cjs <puppeteerRoot> <htmlPath> <inputPath> <outputPath> [backgroundColor] [width]");
  }

  const puppeteer = require(puppeteerRoot);
  const definition = fs.readFileSync(inputPath, "utf8");
  const width = Number.parseInt(widthArg, 10) || 1400;

  const browser = await puppeteer.launch({
    headless: true,
    timeout: 120000,
    protocolTimeout: 120000,
    args: [
      "--no-sandbox",
      "--disable-setuid-sandbox",
      "--disable-dev-shm-usage",
      "--disable-gpu",
      "--allow-file-access-from-files",
    ],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({
      width,
      height: 900,
      deviceScaleFactor: 2,
    });
    page.setDefaultNavigationTimeout(120000);
    page.setDefaultTimeout(120000);

    await page.goto(pathToFileURL(mermaidHtmlPath).href, {
      waitUntil: "load",
      timeout: 120000,
    });

    await page.$eval(
      "body",
      (body, bg) => {
        body.style.background = bg;
        body.style.margin = "0";
        body.style.padding = "16px";
      },
      backgroundColor,
    );

    await page.$eval(
      "#container",
      async (container, def, bg) => {
        const { mermaid, zenuml } = globalThis;
        if (mermaid && zenuml) {
          await mermaid.registerExternalDiagrams([zenuml]);
        }
        mermaid.initialize({ startOnLoad: false });
        const { svg } = await mermaid.render("codex-svg", def, container);
        container.innerHTML = svg;
        const svgEl = container.querySelector("svg");
        if (svgEl && svgEl.style) {
          svgEl.style.backgroundColor = bg;
          svgEl.style.maxWidth = "none";
          svgEl.style.height = "auto";
        }
      },
      definition,
      backgroundColor,
    );

    await page.waitForSelector("#container svg", { timeout: 120000 });
    const svgHandle = await page.$("#container svg");
    if (!svgHandle) {
      throw new Error("Rendered SVG element not found");
    }
    await svgHandle.screenshot({
      path: outputPath,
      omitBackground: false,
    });
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  const message = error && error.stack ? error.stack : String(error);
  process.stderr.write(message);
  process.exit(1);
});
