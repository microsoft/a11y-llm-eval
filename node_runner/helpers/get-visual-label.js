const {
    FIELD_WRAPPER_SELECTOR,
    PRIMARY_SEMANTIC_FIELD_WRAPPER_SELECTOR,
    SECONDARY_SEMANTIC_FIELD_WRAPPER_SELECTOR,
    FALLBACK_FIELD_WRAPPER_SELECTOR,
} = require('./get-form-field-wrapper');
const SOURCE_VISUAL_NEARBY = "VISUAL_NEARBY";
const SOURCE_VISUAL_DISTANT = "VISUAL_DISTANT";
const SOURCE_LABEL_ELEMENT = "LABEL_ELEMENT";
const SOURCE_ARIA_LABELLEDBY = "ARIA_LABELLEDBY";
const SOURCE_PLACEHOLDER = "PLACEHOLDER";
const SOURCE_NONE = "NONE";


// getVisualLabel: returns an representing the visual label associated with a form control element and it's source (e.g. <label>, nearby text, etc.)
const getVisualLabel = async (el, opts = {}) => {
    const { maxDistance = 300 } = opts;

    const visibleLabel = await el.evaluate((el, args) => {
        const {
            FIELD_WRAPPER_SELECTOR,
            PRIMARY_SEMANTIC_FIELD_WRAPPER_SELECTOR,
            SECONDARY_SEMANTIC_FIELD_WRAPPER_SELECTOR,
            FALLBACK_FIELD_WRAPPER_SELECTOR,
            maxDistance,
            SOURCE_VISUAL_NEARBY,
            SOURCE_VISUAL_DISTANT,
            SOURCE_LABEL_ELEMENT,
            SOURCE_ARIA_LABELLEDBY,
            SOURCE_PLACEHOLDER,
            SOURCE_NONE
        } = args;

        const isVisible = (node) => window.axe.commons.dom.isVisible(node, false, true);

        const SUPPLEMENTARY_CLASS_RE = /\b(desc|description|helper|help-text|helper-text|hint|tooltip|supporting|assistive|option-desc|field-note|field-description)\b/;
        const PRIMARY_LABEL_SELECTOR = [
            '.option-title',
            '.label-text',
            '.field-label',
            '.input-label',
            '.control-label',
            '.question-label',
            '.form-label',
            '.legend-text',
            '[data-label-text]',
            '[data-slot="label"]',
        ].join(',');

        function looksLikeSupplementary(node) {
            if (!node || node.nodeType !== Node.ELEMENT_NODE) return false;
            const role = (node.getAttribute && (node.getAttribute('role') || '')).toLowerCase();
            if (role && (role === 'tooltip' || role === 'note' || role === 'status' || role === 'alert')) {
                return true;
            }
            if (node.hasAttribute && (node.hasAttribute('aria-live') || node.hasAttribute('aria-description'))) {
                return true;
            }
            const cls = (node.className || '').toString().toLowerCase();
            if (SUPPLEMENTARY_CLASS_RE.test(cls)) {
                return true;
            }
            return false;
        }

        function collectVisibleText(node, options = {}) {
            const { excludeSupplementary = false } = options;
            if (!node) return '';

            if (node.nodeType === Node.ELEMENT_NODE && excludeSupplementary && looksLikeSupplementary(node)) {
                return '';
            }

            const collect = (n) => {
                if (!n) return '';

                if (n.nodeType === Node.ELEMENT_NODE) {
                    if (excludeSupplementary && looksLikeSupplementary(n)) {
                        return '';
                    }

                    if (window.getComputedStyle) {
                        const cs = window.getComputedStyle(n);
                        if (cs && cs.color) {
                            const color = cs.color.trim().toLowerCase();
                            if (color.startsWith('rgba')) {
                                const m = color.match(/rgba\([^,]+,[^,]+,[^,]+,\s*([0-9.]+)\)/);
                                if (m && parseFloat(m[1]) === 0) {
                                    return '';
                                }
                            }
                            if (color === 'transparent') {
                                return '';
                            }
                        }
                    }
                }

                if (n.nodeType === Node.TEXT_NODE) {
                    return (n.nodeValue || '');
                }

                let buffer = '';
                for (let child = n.firstChild; child; child = child.nextSibling) {
                    buffer += collect(child);
                }
                return buffer;
            };

            let text = collect(node).replace(/\s+/g, ' ').trim();

            if (node.nodeType === Node.ELEMENT_NODE && window.getComputedStyle) {
                const pseudoContent = (which) => {
                    const cs = window.getComputedStyle(node, which);
                    if (!cs) return '';
                    let c = cs.getPropertyValue('content');
                    if (!c || c === 'none' || c === 'normal') return '';
                    c = c.trim();
                    if ((c.startsWith('"') && c.endsWith('"')) || (c.startsWith("'") && c.endsWith("'"))) {
                        c = c.slice(1, -1);
                    }
                    return c.trim();
                };

                const before = pseudoContent('::before');
                const after = pseudoContent('::after');

                const parts = [];
                if (before) parts.push(before);
                if (text) parts.push(text);
                if (after) parts.push(after);

                if (parts.length) {
                    text = parts.join(' ');
                }
            }

            return text;
        }

        function labelTextOf(node) {
            if (!node) return '';

            if (node.nodeType === Node.ELEMENT_NODE) {
                const candidates = [];
                if (node.matches && node.matches(PRIMARY_LABEL_SELECTOR) && isVisible(node) && !looksLikeSupplementary(node)) {
                    candidates.push(node);
                }
                if (node.querySelectorAll) {
                    for (const candidate of node.querySelectorAll(PRIMARY_LABEL_SELECTOR)) {
                        if (isVisible(candidate) && !looksLikeSupplementary(candidate)) {
                            candidates.push(candidate);
                        }
                    }
                }

                const filteredCandidates = candidates.filter((candidate, index) => {
                    return !candidates.some((other, otherIndex) => otherIndex !== index && other.contains(candidate));
                });

                if (filteredCandidates.length > 0) {
                    const parts = [];
                    for (const candidate of filteredCandidates) {
                        const text = collectVisibleText(candidate, { excludeSupplementary: true });
                        if (text) parts.push(text);
                    }
                    const combined = parts.join(' ').replace(/\s+/g, ' ').trim();
                    if (combined) {
                        return combined;
                    }
                }
            }

            return collectVisibleText(node, { excludeSupplementary: true });
        }

        // Use a single parts array for programmatic labels first
        const parts = [];

        // 1) aria-labelledby
        const labelledby = el.getAttribute && el.getAttribute('aria-labelledby');
        if (labelledby) {
            for (const id of labelledby.split(/\s+/)) {
                const target = document.getElementById(id);
                if (target && isVisible(target)) {
                    const t = labelTextOf(target);
                    if (t) parts.push(t);
                }
            }
        }
        // If we already have visible programmatic labels, return them
        if (parts.length) return {text: parts.join(' '), source: SOURCE_ARIA_LABELLEDBY};

        // 2) Programmatic <label> elements via el.labels
        try {
            if (el.labels && el.labels.length) {
                for (const lab of el.labels) {
                    if (isVisible(lab)) {
                        const t = labelTextOf(lab);
                        if (t) parts.push(t);
                    }
                }
            }
        } catch (e) {}

        // If we already have visible programmatic labels, return them
        if (parts.length) return {text: parts.join(' '), source: SOURCE_LABEL_ELEMENT};

        // 4) Fallback visual search: find a nearby visible text node in a "form field" wrapper
        const wrapper =
            el.closest(PRIMARY_SEMANTIC_FIELD_WRAPPER_SELECTOR)
            || el.closest(SECONDARY_SEMANTIC_FIELD_WRAPPER_SELECTOR)
            || el.closest(FALLBACK_FIELD_WRAPPER_SELECTOR)
            || el.closest(FIELD_WRAPPER_SELECTOR)
            || document.body;

        // Build list of candidate elements that contain visible text, are not the control, and are not error-like
        const candidates = [];
        const inputRect = el.getBoundingClientRect();

        // helper: is this element likely an error message?
        function looksLikeNonLabel(node) {
            if (!node) return false;
            const role = node.getAttribute && node.getAttribute('role');
            if (role && (role === 'alert' || role === 'status')) return true;
            if (node.hasAttribute && node.hasAttribute('aria-live')) return true;
            const cls = (node.className || '').toString().toLowerCase();
            if (/\b(error|invalid|form-error|field-error|error-message|validation)\b/.test(cls)) return true; // likely an error message
            if (/\b(hint|helper|tooltip|description|help)\b/.test(cls)) return true; // likely a hint/helper, not a label
            if (node.tagName === 'SMALL') return true; // often used for hints/errors
            return false;
        }

        // gather aria-describedby ids to avoid picking described content (often hints/errors)
        const described = new Set((el.getAttribute && (el.getAttribute('aria-describedby') || '')).split(/\s+/).filter(Boolean));

        // iterate visible text-bearing elements in wrapper
        const walker = document.createTreeWalker(wrapper, NodeFilter.SHOW_ELEMENT, {
            acceptNode(node) {
                if (node === el) return NodeFilter.FILTER_REJECT;
                if (!isVisible(node)) return NodeFilter.FILTER_REJECT;
                const txt = labelTextOf(node);
                if (!txt) return NodeFilter.FILTER_REJECT;
                if (looksLikeNonLabel(node)) return NodeFilter.FILTER_REJECT;
                if (described.has(node.id)) return NodeFilter.FILTER_REJECT;
                return NodeFilter.FILTER_ACCEPT;
            }
        }, false);

        while (walker.nextNode()) {
            const node = walker.currentNode;
            // avoid nodes that contain the input (we want labels outside of the input)
            if (node.contains(el)) continue;
            const rect = node.getBoundingClientRect();
            // compute center distance (px)
            const dx = (rect.left + rect.right) / 2 - (inputRect.left + inputRect.right) / 2;
            const dy = (rect.top + rect.bottom) / 2 - (inputRect.top + inputRect.bottom) / 2;
            const distance = Math.hypot(dx, dy);
            candidates.push({ node, text: labelTextOf(node), rect, distance, dy });
        }

        if (candidates.length === 0) {
            // return the placeholder if there is one
            const placeholder = el.getAttribute && el.getAttribute('placeholder');
            if (placeholder) {
                return {text: placeholder, source: SOURCE_PLACEHOLDER};
            }
            return {text: '', source: SOURCE_NONE};
        }

        // filter to those within reasonable maxDistance
        const nearby = candidates.filter(c => c.distance <= maxDistance);

        if (nearby.length === 0) {
            // otherwise, if none within maxDistance, return the top 1 candidate (closest) anyway
            const best = candidates[0];
            return best ? {text: best.text, source: SOURCE_VISUAL_DISTANT} : {text: '', source: SOURCE_NONE};
        }

        // Join nearby matches and return
        return {text: nearby.map(c => c.text).join(' '), source: SOURCE_VISUAL_NEARBY};
    }, {
        FIELD_WRAPPER_SELECTOR,
        PRIMARY_SEMANTIC_FIELD_WRAPPER_SELECTOR,
        SECONDARY_SEMANTIC_FIELD_WRAPPER_SELECTOR,
        FALLBACK_FIELD_WRAPPER_SELECTOR,
        maxDistance,
        SOURCE_VISUAL_NEARBY,
        SOURCE_VISUAL_DISTANT,
        SOURCE_LABEL_ELEMENT,
        SOURCE_ARIA_LABELLEDBY,
        SOURCE_PLACEHOLDER,
        SOURCE_NONE
    });

    return visibleLabel || '';
}

module.exports.getVisualLabel = getVisualLabel;
module.exports.SOURCE_VISUAL_NEARBY = SOURCE_VISUAL_NEARBY;
module.exports.SOURCE_VISUAL_DISTANT = SOURCE_VISUAL_DISTANT;
module.exports.SOURCE_LABEL_ELEMENT = SOURCE_LABEL_ELEMENT;
module.exports.SOURCE_ARIA_LABELLEDBY = SOURCE_ARIA_LABELLEDBY;
module.exports.SOURCE_PLACEHOLDER = SOURCE_PLACEHOLDER;
module.exports.SOURCE_NONE = SOURCE_NONE;