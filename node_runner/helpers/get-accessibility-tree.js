const AX_MARKER_ATTRIBUTE = 'data-a11y-llm-ax-marker';

const cdpSessionByPage = new WeakMap();

const emptyNodeInfo = () => ({
    role: '',
    name: '',
    description: '',
});

const normalizeText = (value) => (value || '').toString().replace(/\s+/g, ' ').trim();

const getPageForTarget = async (target) => {
    if (target && typeof target.page === 'function') {
        return target.page();
    }

    if (target && typeof target.ownerFrame === 'function') {
        const frame = await target.ownerFrame();
        if (frame && typeof frame.page === 'function') {
            return frame.page();
        }
    }

    throw new Error('Unable to resolve Playwright page for accessibility lookup');
};

const getCDPSession = async (page) => {
    let sessionPromise = cdpSessionByPage.get(page);
    if (!sessionPromise) {
        sessionPromise = page.context().newCDPSession(page);
        cdpSessionByPage.set(page, sessionPromise);
    }

    return sessionPromise;
};

const markTargetNode = async (target, markerValue) => {
    return target.evaluate((el, args) => {
        const { attrName, markerValue } = args;
        const hadAttribute = el.hasAttribute(attrName);
        const previousValue = el.getAttribute(attrName);
        el.setAttribute(attrName, markerValue);
        return { hadAttribute, previousValue };
    }, {
        attrName: AX_MARKER_ATTRIBUTE,
        markerValue,
    });
};

const restoreTargetNode = async (target, markerState) => {
    if (!markerState) {
        return;
    }

    await target.evaluate((el, args) => {
        const { attrName, hadAttribute, previousValue } = args;
        if (hadAttribute) {
            el.setAttribute(attrName, previousValue || '');
            return;
        }

        el.removeAttribute(attrName);
    }, {
        attrName: AX_MARKER_ATTRIBUTE,
        hadAttribute: markerState.hadAttribute,
        previousValue: markerState.previousValue,
    });
};

/**
 * Core: resolve a Playwright ElementHandle / Locator to its raw CDP
 * accessibility node.  Returns the AXNode object, or null when the
 * element cannot be found.
 *
 * A temporary data-attribute marker is stamped on the DOM element so
 * the CDP DOM.querySelector can locate it by nodeId.  The marker is
 * always cleaned up in the finally block.
 */
const getAXNode = async (target) => {
    if (!target) {
        return null;
    }

    const markerValue = `ax-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
    let markerState = null;

    try {
        const page = await getPageForTarget(target);
        const session = await getCDPSession(page);

        markerState = await markTargetNode(target, markerValue);

        const { root } = await session.send('DOM.getDocument');
        const { nodeId } = await session.send('DOM.querySelector', {
            nodeId: root.nodeId,
            selector: `[${AX_MARKER_ATTRIBUTE}="${markerValue}"]`,
        });

        if (!nodeId) {
            return null;
        }

        const { nodes = [] } = await session.send('Accessibility.getPartialAXTree', {
            nodeId,
            fetchRelatives: false,
        });

        return nodes[0] || null;
    } catch {
        return null;
    } finally {
        try {
            await restoreTargetNode(target, markerState);
        } catch {
            // Ignore cleanup failures if the node is detached or the page navigated.
        }
    }
};

const getAccessibilityNodeInfo = async (target) => {
    const axNode = await getAXNode(target);
    if (!axNode) {
        return emptyNodeInfo();
    }
    return {
        role: normalizeText(axNode.role && axNode.role.value),
        name: normalizeText(axNode.name && axNode.name.value),
        description: normalizeText(axNode.description && axNode.description.value),
    };
};

const getAccessibleName = async (target) => {
    const node = await getAccessibilityNodeInfo(target);
    return node.name;
};

const getAccessibleDescription = async (target) => {
    const node = await getAccessibilityNodeInfo(target);
    return node.description;
};

/**
 * Returns true when the element is present in the accessibility tree
 * (i.e. exposed to assistive technology).  Uses the CDP `ignored` flag
 * which accounts for aria-hidden, inert, display:none, visibility:hidden,
 * the <dialog> open state, and every other browser-level hiding mechanism.
 */
const isExposedToAccessibilityTree = async (target) => {
    const axNode = await getAXNode(target);
    return axNode != null && !axNode.ignored;
};

module.exports.getAXNode = getAXNode;
module.exports.getAccessibilityNodeInfo = getAccessibilityNodeInfo;
module.exports.getAccessibleName = getAccessibleName;
module.exports.getAccessibleDescription = getAccessibleDescription;
module.exports.isExposedToAccessibilityTree = isExposedToAccessibilityTree;