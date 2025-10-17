#!/usr/bin/env node
// Playwright + axe-core executor (mirrors runner.js for Puppeteer).
// NOTE: Initially Chromium-only; future work may add firefox/webkit via arg/env.

const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");
const axeSource = require("axe-core").source;

async function main() {
  const [,, htmlPath, testJsPath, outJsonPath, screenshotPath] = process.argv;
  if (!htmlPath || !testJsPath || !outJsonPath) {
    console.error("Usage: node playwright_runner.js <htmlPath> <testJsPath> <outJsonPath> [screenshotPath]");
    process.exit(2);
  }
  const html = fs.readFileSync(htmlPath, "utf-8");
  let testFn;
  try {
    testFn = require(path.resolve(testJsPath));
  } catch (e) {
    console.error("Failed loading test file:", e);
    testFn = {};
  }

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  const consoleLogs = [];
  page.on("console", msg => consoleLogs.push(msg.text()));

  const start = Date.now();
  let testFunctionResult = { status: "error", assertions: [] };
  let axeResult = null;
  let errorMsg = null;

  try {
    await page.setContent(html, { waitUntil: "load" });
    await page.addScriptTag({ content: axeSource });

    if (!testFn.run || typeof testFn.run !== 'function') {
      testFunctionResult = { status: 'error', assertions: [], error: 'No run export (expected module.exports.run = async ({ page, assert }) => {...})' };
    } else {
      const collected = [];
      const assert = async (name, fn, opts = {}) => {
        const { type = 'R' } = opts;
        let normalizedType = (type || 'R').toUpperCase();
        if (!['R','BP'].includes(normalizedType)) normalizedType = 'R';
        try {
          const r = await fn();
          // Allow boolean or object { pass, message }
          let passVal = r;
          let message;
          if (r && typeof r === 'object' && 'pass' in r) {
            passVal = r.pass;
            message = r.message;
          }
          collected.push({ name, status: passVal ? 'pass' : 'fail', message, type: normalizedType });
        } catch (e) {
          collected.push({ name, status: 'fail', message: e.message, type: normalizedType });
        }
      };

      const runStart = Date.now();
      try {
        await testFn.run({ page, assert, utils: { /* future helpers */ } });
      } catch (e) {
        errorMsg = e.stack || e.message;
      }
      const duration_ms = Date.now() - runStart;

      // Normalize & determine status based only on requirement failures
      const hasReqFailure = collected.some(a => a.type === 'R' && a.status === 'fail');
      testFunctionResult = {
        status: hasReqFailure ? 'fail' : 'pass',
        assertions: collected,
        duration_ms
      };
    }

    axeResult = await page.evaluate(async () => {
      const results = await window.axe.run();

      // Separate WCAG violations from best practice violations
      const wcagViolations = [];
      const bestPracticeViolations = [];
      
      results.violations.forEach(v => {
        const mappedViolation = {
          id: v.id,
            impact: v.impact,
            description: v.description,
            helpUrl: v.helpUrl,
            nodes: v.nodes.map(n => ({ html: n.html, target: n.target })),
            tags: v.tags
        };
        if (v.tags.includes('best-practice')) {
          bestPracticeViolations.push(mappedViolation);
        } else {
          wcagViolations.push(mappedViolation);
        }
      });
      return {
        violation_count: wcagViolations.length,
        violations: wcagViolations,
        best_practice_count: bestPracticeViolations.length,
        best_practice_violations: bestPracticeViolations
      };
    });

    if (screenshotPath) {
      try {
        await page.screenshot({ path: screenshotPath, fullPage: true });
      } catch (e) {
        console.error('Screenshot failed:', e.message);
      }
    }
  } catch (e) {
    errorMsg = e.stack || e.message;
    if (testFunctionResult.status === "error") {
      testFunctionResult.error = errorMsg;
    }
  } finally {
    await browser.close();
  }

  const out = {
    engine: 'playwright',
    browser: 'chromium',
    testFunctionResult,
    axeResult,
    consoleLogs,
    error: errorMsg,
    total_duration_ms: Date.now() - start
  };
  fs.writeFileSync(outJsonPath, JSON.stringify(out, null, 2), "utf-8");
}

main().catch(e => {
  console.error(e);
  process.exit(1);
});
