#!/usr/bin/env node
// Playwright + axe-core executor (mirrors runner.js for Puppeteer).
// NOTE: Initially Chromium-only; future work may add firefox/webkit via arg/env.

const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");
const axeSource = require("axe-core").source;
const merge = require('deepmerge')
const testFormControls = require('./helpers/test-form-controls');

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
  let launchOptions = { headless: true };
  if (process.env.A11Y_LLM_EVAL_DEBUG === "1") {
    launchOptions = { headless: false, slowMo: 1000 };
  }

  const browser = await chromium.launch(launchOptions);
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  const consoleLogs = [];
  page.on("console", msg => consoleLogs.push(msg.text()));

  const start = Date.now();
  let testFunctionResult = { status: "error", assertions: [] };
  let axeResult = null;
  let errorMsg = null;

  async function loadHTML() {
    await page.reload();
    await page.setContent(html, { waitUntil: "load" });
    await page.addScriptTag({ content: axeSource });
    await page.evaluate(() => { window.axe.setup();});
  }

  async function runAxeOnPage(page) {
    return await page.evaluate(async () => {
      return await window.axe.run();
    });
  }

  const utils = {
    reload: loadHTML,
    runAxeOnPage,
    merge,
    testFormControls,
    testTextInputs: testFormControls,
  };

  try {
    await loadHTML();

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
          // Allow boolean, object { pass, message }, or object { status, message }
          let status;
          let message;
          if (r && typeof r === 'object' && 'status' in r) {
            status = String(r.status || '').toLowerCase();
            message = r.message;
          } else if (r && typeof r === 'object' && 'pass' in r) {
            status = r.pass ? 'pass' : 'fail';
            message = r.message;
          } else {
            status = r ? 'pass' : 'fail';
          }

          if (!['pass', 'fail', 'na'].includes(status)) {
            status = 'fail';
          }
          if (status === 'fail' && (!message || !String(message).trim())) {
            message = `Assertion failed: ${name}`;
          }
          collected.push({ name, status, message, type: normalizedType });
        } catch (e) {
          collected.push({ name, status: 'fail', message: e.message, type: normalizedType });
        }
      };

      const runStart = Date.now();
      try {
        await testFn.run({ page, assert, utils });
      } catch (e) {
        errorMsg = e.stack || e.message;
      }
      const duration_ms = Date.now() - runStart;

      // Normalize & determine status based only on requirement failures
      const hasAssertionFailure = collected.some(a => a.type === 'R' && a.status === 'fail');
      const totalAssertionFailures = collected.filter(a => a.type === 'R' && a.status === 'fail').length;
      const totalAssertionBpFailures = collected.filter(a => a.type === 'BP' && a.status === 'fail').length;
      const totalAssertionNA = collected.filter(a => a.type === 'R' && a.status === 'na').length;
      const totalAssertionBpNA = collected.filter(a => a.type === 'BP' && a.status === 'na').length;
      testFunctionResult = {
        status: hasAssertionFailure ? 'fail' : 'pass',
        assertions: collected,
        duration_ms,
        total_assertion_failures: totalAssertionFailures,
        total_assertion_bp_failures: totalAssertionBpFailures,
        total_assertion_na: totalAssertionNA,
        total_assertion_bp_na: totalAssertionBpNA
      };
    }

    const processAxeResults = (results) => {
      // Separate WCAG violations from best practice violations
      const wcagViolations = [];
      const bestPracticeViolations = [];
      
      let wcagCount = 0;
      let bestPracticeCount = 0;
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
          bestPracticeCount += mappedViolation.nodes.length;
        } else {
          wcagViolations.push(mappedViolation);
          wcagCount += mappedViolation.nodes.length;
        }
      });
      return {
        failure_count: wcagCount,
        failures: wcagViolations,
        best_practice_count: bestPracticeCount,
        best_practice_failures: bestPracticeViolations
      };
    }

    if (screenshotPath) {
      try {
        await page.screenshot({ path: screenshotPath, fullPage: true });
      } catch (e) {
        console.error('Screenshot failed:', e.message);
      }
    }

    axeResult = await runAxeOnPage(page);

    if (testFn.runAxe && typeof testFn.runAxe === 'function') {
      const axeCustomResult = await testFn.runAxe({ page, utils});
      if (axeCustomResult && typeof axeCustomResult === 'object') {
        axeResult = merge(axeResult || {}, axeCustomResult);
      }
    }

    axeResult = processAxeResults(axeResult);
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
