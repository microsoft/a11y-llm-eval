// New harness signature with dependency injection
module.exports.run = async ({ page, assert }) => {
  await assert("Has a skip navigation link", async () => {
    const main = page.getByRole('main');
    if ((await main.count()) !== 1) {
      return false;
    }

    const skipLink = page.getByRole('link', {
      name: /(?:skip|jump|go)(?:\s+(?:to\s+)?)?(?:main|main content|content|nav|navigation|header)\b/i,
    });
    const count = await skipLink.count();
    if (count < 1) {
      return false;
    }

    const isValidSkipTarget = await page.evaluate(() => {
      const skipNamePattern = /(?:skip|jump|go)(?:\s+(?:to\s+)?)?(?:main|main content|content|nav|navigation|header)\b/i;

      const normalizeText = (value) => (value || '').toString().replace(/\s+/g, ' ').trim();
      const getAccessibleName = (element) => {
        const ariaLabel = normalizeText(element.getAttribute && element.getAttribute('aria-label'));
        if (ariaLabel) return ariaLabel;
        return normalizeText(element.textContent || element.innerText || '');
      };

      const isFocusable = (element) => {
        if (!element || element.nodeType !== Node.ELEMENT_NODE) return false;

        const tabindexAttr = element.getAttribute('tabindex');
        if (tabindexAttr !== null) {
          const tabindex = Number.parseInt(tabindexAttr, 10);
          return !Number.isNaN(tabindex) && tabindex >= -1;
        }

        if (element.matches('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, iframe, audio[controls], video[controls]')) {
          return true;
        }

        if (element.hasAttribute('contenteditable') && element.getAttribute('contenteditable') !== 'false') {
          return true;
        }

        return false;
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
        return false;
      }

      const firstMeaningfulDescendant = getFirstMeaningfulDescendant(mainElement);
      const links = Array.from(document.querySelectorAll('a[href^="#"], [role="link"][href^="#"]'));

      return links.some((link) => {
        const name = getAccessibleName(link);
        if (!skipNamePattern.test(name)) {
          return false;
        }

        const href = link.getAttribute('href') || '';
        if (!href.startsWith('#') || href.length <= 1) {
          return false;
        }

        const target = document.getElementById(href.slice(1));
        if (!target) {
          return false;
        }

        const targetInMain = target === mainElement || mainElement.contains(target);
        if (!targetInMain) {
          return false;
        }

        if (!isFocusable(target)) {
          return false;
        }

        if (target === mainElement) {
          return true;
        }

        if (!firstMeaningfulDescendant) {
          return true;
        }

        const relation = target.compareDocumentPosition(firstMeaningfulDescendant);
        return target === firstMeaningfulDescendant || !!(relation & Node.DOCUMENT_POSITION_FOLLOWING);
      });
    });

    return isValidSkipTarget;
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
    let footer = await page.getByRole('contentinfo');
    return (await footer.count()) === 1;
  });

  return {}; // assertions collected via injected assert
};
