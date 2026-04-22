// New harness signature with dependency injection
module.exports.run = async ({ page, assert }) => {
  await assert("Has a skip navigation link", async () => {
    const main = page.getByRole('main');
    if ((await main.count()) !== 1) {
      return { pass: false, message: 'Expected exactly one element with role="main".' };
    }

    const skipLink = page.getByRole('link', {
      name: /(?:skip|jump|go)(?:\s+(?:to\s+)?)?(?:main|main content|content|nav|navigation|header)\b/i,
    });
    const count = await skipLink.count();
    if (count < 1) {
      return { pass: false, message: 'No skip navigation link found (expected a link with accessible name like "Skip to main content").' };
    }

    const evalResult = await page.evaluate(() => {
      const skipNamePattern = /(?:skip|jump|go)(?:\s+(?:to\s+)?)?(?:main|main content|content|nav|navigation|header)\b/i;

      const normalizeText = (value) => (value || '').toString().replace(/\s+/g, ' ').trim();
      const getAccessibleName = (element) => {
        const ariaLabel = normalizeText(element.getAttribute && element.getAttribute('aria-label'));
        if (ariaLabel) return ariaLabel;
        return normalizeText(element.textContent || element.innerText || '');
      };

      const getFirstMeaningfulDescendant = (mainElement) => {
        const walker = document.createTreeWalker(mainElement, NodeFilter.SHOW_ELEMENT, {
          acceptNode(node) {
            if (node === mainElement) return NodeFilter.FILTER_SKIP;
            if (node.matches('script, style, template')) return NodeFilter.FILTER_REJECT;

            const text = normalizeText(node.textContent || node.innerText || '');
            if (!text && !node.matches('a, button, input, select, textarea, img, h1, h2, h3, h4, h5, h6, [tabindex]')) {
              return NodeFilter.FILTER_SKIP;
            }

            return NodeFilter.FILTER_ACCEPT;
          }
        });

        return walker.nextNode() ? walker.currentNode : null;
      };

      const mainElement = document.querySelector('main, [role="main"]');
      if (!mainElement) {
        return { pass: false, reason: 'no-main' };
      }

      const firstMeaningfulDescendant = getFirstMeaningfulDescendant(mainElement);
      const links = Array.from(document.querySelectorAll('a[href^="#"], [role="link"][href^="#"]'));

      const reasons = [];
      for (const link of links) {
        const name = getAccessibleName(link);
        if (!skipNamePattern.test(name)) {
          continue;
        }

        const href = link.getAttribute('href') || '';
        if (!href.startsWith('#') || href.length <= 1) {
          reasons.push({ href, reason: 'empty-href' });
          continue;
        }

        const target = document.getElementById(href.slice(1));
        if (!target) {
          reasons.push({ href, reason: 'target-missing' });
          continue;
        }

        const targetInMain = target === mainElement || mainElement.contains(target);
        if (!targetInMain) {
          reasons.push({ href, reason: 'target-not-in-main', targetTag: target.tagName.toLowerCase() });
          continue;
        }

        if (target === mainElement) {
          return { pass: true };
        }

        if (!firstMeaningfulDescendant) {
          return { pass: true };
        }

        const relation = target.compareDocumentPosition(firstMeaningfulDescendant);
        if (target === firstMeaningfulDescendant || !!(relation & Node.DOCUMENT_POSITION_FOLLOWING)) {
          return { pass: true };
        }
        reasons.push({ href, reason: 'target-after-first-content' });
      }

      return { pass: false, reasons };
    });

    if (evalResult.pass) {
      return true;
    }

    const reasons = evalResult.reasons || [];
    if (evalResult.reason === 'no-main') {
      return { pass: false, message: 'No <main> or [role="main"] element found.' };
    }
    if (reasons.some((r) => r.reason === 'target-missing')) {
      return { pass: false, message: `Skip link href does not resolve to an element in the document (${reasons.map((r) => r.href).join(', ')}).` };
    }
    if (reasons.some((r) => r.reason === 'target-not-in-main')) {
      return { pass: false, message: 'Skip link target is outside <main>.' };
    }
    if (reasons.some((r) => r.reason === 'target-after-first-content')) {
      return { pass: false, message: 'Skip link target is positioned after the first meaningful content inside <main>.' };
    }
    if (reasons.some((r) => r.reason === 'empty-href')) {
      return { pass: false, message: 'Skip link href is empty or invalid.' };
    }
    return { pass: false, message: 'Skip navigation link is not valid.' };
  });

  await assert("Has an h1", async () => {
    const h1 = await page.$$eval("h1", els => els.length);
    const roleH1 = await page.$$eval("[role='heading'][aria-level='1']", els => els.length);
    return (h1 + roleH1) >= 1;
  });

  await assert("Has single h1", async () => {
    const h1 = await page.getByRole('heading', { level: 1 });
    const count = await h1.count();
    return count === 1;
  }, {type: 'BP'});

  await assert("Has at least one h2", async () => {
    const h2 = await page.getByRole('heading', { level: 2 });
    const count = await h2.count();
    return count >= 1;
  });

  await assert("Has a single banner", async () => {
    const banner = await page.getByRole('banner');
    return (await banner.count()) === 1;
  });

  await assert("Has a single maincontent", async () => {
    const main = await page.getByRole('main');
    return (await main.count()) === 1;
  });

  await assert("Has at least one navigation", async () => {
    const nav = await page.getByRole('navigation');
    return (await nav.count()) >= 1;
  });

  await assert("Has a single footer", async () => {
    const footerCount = await page.getByRole('contentinfo').count();
    if (footerCount === 1) return true;
    if (footerCount > 1) {
      return { pass: false, message: `Expected exactly one contentinfo landmark; found ${footerCount}.` };
    }

    // No <footer> / [role="contentinfo"]. Only require one if the page has content
    // that functionally acts as a footer (copyright, legal, site-wide links, etc.).
    const hasFooterLikeContent = await page.evaluate(() => {
      const main = document.querySelector('main, [role="main"]');
      const body = document.body;
      if (!body) return false;

      const isIgnorable = (el) => el && el.matches && el.matches('script, style, template, noscript, link, meta');
      const visibleText = (el) => ((el && (el.textContent || el.innerText)) || '').replace(/\s+/g, ' ').trim();

      // Any substantive content that comes after <main> (at any ancestor level) implies a footer region.
      if (main) {
        let cursor = main;
        while (cursor && cursor !== body) {
          let sib = cursor.nextElementSibling;
          while (sib) {
            if (!isIgnorable(sib) && visibleText(sib)) return true;
            sib = sib.nextElementSibling;
          }
          cursor = cursor.parentElement;
        }
      }

      // Elements whose class/id/name explicitly marks them as a footer region (outside <main>).
      const footerIdent = /(?:^|[-_\s])footer(?:$|[-_\s])/i;
      const candidates = body.querySelectorAll('[class], [id], [data-testid]');
      for (const el of candidates) {
        if (main && main.contains(el)) continue;
        const idents = [el.getAttribute('class') || '', el.getAttribute('id') || '', el.getAttribute('data-testid') || ''];
        if (idents.some((v) => footerIdent.test(v)) && visibleText(el)) return true;
      }

      // Copyright / legal / explicit "footer" text anywhere outside <main> also implies a footer region.
      const pattern = /(?:\u00a9|\(c\)|copyright|all rights reserved|privacy policy|terms of service|terms and conditions|\bfooter\b)/i;
      const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT, {
        acceptNode(node) {
          if (main && main.contains(node)) return NodeFilter.FILTER_REJECT;
          const text = (node.nodeValue || '').trim();
          if (!text) return NodeFilter.FILTER_SKIP;
          return pattern.test(text) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
        },
      });
      return !!walker.nextNode();
    });

    if (!hasFooterLikeContent) {
      return {
        status: 'na',
        message: 'Page has no footer-like content (no copyright, legal text, or site-wide content outside <main>); a contentinfo landmark is not required.',
      };
    }

    return {
      pass: false,
      message: 'Page has footer-like content but no contentinfo landmark. Wrap the footer content in <footer> or add role="contentinfo".',
    };
  });

  return {}; // assertions collected via injected assert
};
