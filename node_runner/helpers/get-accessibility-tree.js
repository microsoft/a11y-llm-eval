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

const getAccessibilityNodeInfo = async (target) => {
    if (!target) {
        return emptyNodeInfo();
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
            return emptyNodeInfo();
        }

        const { nodes = [] } = await session.send('Accessibility.getPartialAXTree', {
            nodeId,
            fetchRelatives: false,
        });

        const axNode = nodes[0];
        return {
            role: normalizeText(axNode && axNode.role && axNode.role.value),
            name: normalizeText(axNode && axNode.name && axNode.name.value),
            description: normalizeText(axNode && axNode.description && axNode.description.value),
        };
    } catch {
        return emptyNodeInfo();
    } finally {
        try {
            await restoreTargetNode(target, markerState);
        } catch {
            // Ignore cleanup failures if the node is detached or the page navigated.
        }
    }
};

const getAccessibleName = async (target) => {
    const node = await getAccessibilityNodeInfo(target);
    return node.name;
};

const getAccessibleDescription = async (target) => {
    const node = await getAccessibilityNodeInfo(target);
    return node.description;
};

module.exports.getAccessibilityNodeInfo = getAccessibilityNodeInfo;
module.exports.getAccessibleName = getAccessibleName;
module.exports.getAccessibleDescription = getAccessibleDescription;