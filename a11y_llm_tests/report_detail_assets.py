"""Detail report asset and template constants."""

DETAIL_PAGE_STYLE = """
body {
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 16px;
  background: #111827;
  color: #f9fafb;
  margin: 0;
  line-height: 1.6;
}
a { color: #659fff; }
main {
  max-width: 1200px;
  margin: 0 auto;
  padding: 1.5rem;
}
.breadcrumbs {
  margin-bottom: 1rem;
}
.prompt-block {
  white-space: pre-wrap;
  background: #283446;
  padding: 0.85rem 1rem;
  border-radius: 0.75rem;
  border: 1px solid #334155;
}
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: flex-end;
  padding: 1rem;
  background: #1f2937;
  border: 1px solid #334155;
  border-radius: 0.75rem;
  margin-bottom: 1rem;
}
.filters label {
  display: flex;
  flex-direction: column;
  font-weight: 600;
  font-size: 0.95rem;
}
.filters select {
  margin-top: 0.35rem;
  padding: 0.4rem 0.6rem;
  font-size: 0.95rem;
  border-radius: 0.5rem;
  border: 1px solid #475569;
  background: #283446;
  color: #f9fafb;
}
.filters button {
  padding: 0.45rem 0.9rem;
  font-size: 0.95rem;
  border-radius: 0.5rem;
  border: none;
  background: #006aec;
  color: #ffffff;
  font-weight: 600;
}
.filters-summary {
  margin: 1rem 0 0.5rem;
  font-size: 0.95rem;
  color: #f9fafb;
  font-weight: 600;
}
.samples {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 1.25rem;
  margin-top: 1rem;
}
.sample-card {
  border-radius: 0.9rem;
  border: 1px solid #334155;
  padding: 1rem;
  background: #1f2937;
}
.badge-pass, .badge-fail, .badge-na {
  display: inline-flex;
  align-items: center;
  font-weight: 600;
  font-size: 0.85rem;
  padding: 0.15rem 0.6rem;
  border-radius: 999px;
}
.badge-pass { background: #0a8336; color: #ffffff; }
.badge-fail { background: #a80000; color: #ffffff; }
.badge-na { background: #fbbf24; color: #1f2937; }
details {
  border: 1px solid #334155;
  border-radius: 0.75rem;
  padding: 0.75rem 1rem;
  margin-bottom: 1rem;
  background: #1f2937;
}
details summary {
  cursor: pointer;
}
figure img {
  width: 100%;
  max-width: 320px;
  border-radius: 0.75rem;
  border: 1px solid #334155;
}
.conversation-dialog {
  width: min(960px, calc(100vw - 2rem));
  max-height: calc(100vh - 4rem);
  border: 1px solid #334155;
  border-radius: 0.85rem;
  padding: 0;
  background: #111827;
  color: #f9fafb;
}
.conversation-dialog::backdrop {
  background: rgba(15, 23, 42, 0.8);
}
.conversation-dialog-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid #334155;
}
.conversation-dialog-body {
  padding: 1rem 1.25rem 1.25rem;
  overflow: auto;
}
.conversation-dialog-close,
.conversation-btn {
  padding: 0.45rem 0.9rem;
  font-size: 0.95rem;
  border-radius: 0.5rem;
  border: none;
  background: #006aec;
  color: #ffffff;
  font-weight: 600;
}
.transcript-turns {
  display: grid;
  gap: 0.35rem;
}
.transcript-turn {
  padding: 0.35rem 0.65rem;
  border-left: 3px solid #334155;
  background: rgba(40, 52, 70, 0.5);
  border-radius: 0 0.4rem 0.4rem 0;
}
.transcript-turn-header {
  margin: 0;
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
}
.transcript-turn-msg,
.transcript-tool-list {
  margin: 0.15rem 0;
  color: #cbd5f5;
}
.assertion-message-list {
  margin: 0.35rem 0 0;
}
"""

DETAIL_BROWSER_SCRIPT = """
function initDetailBrowsers(root) {
  const browsers = Array.from(root.querySelectorAll('[data-detail-browser]'));

  browsers.forEach(function (browser) {
    if (browser.dataset.filtersInitialized === 'true') {
      return;
    }
    browser.dataset.filtersInitialized = 'true';

    const modelFilter = browser.querySelector('[data-model-filter]');
    const variantFilter = browser.querySelector('[data-variant-filter]');
    const resultFilter = browser.querySelector('[data-result-filter]');
    const resetButton = browser.querySelector('[data-reset-filters]');
    const modelSections = Array.from(browser.querySelectorAll('[data-model-group]'));
    const allCards = Array.from(browser.querySelectorAll('.sample-card'));
    const noResultsMessage = browser.querySelector('[data-no-results-message]');
    const countEl = browser.querySelector('[data-filter-count]');
    const nameFilter = browser.querySelector('[data-assertion-name-filter]');
    const statusFilter = browser.querySelector('[data-assertion-status-filter]');
    const resetAssertionButton = browser.querySelector('[data-assertion-reset-filters]');
    const assertionCountEl = browser.querySelector('[data-assertion-filter-count]');
    const totalCardCount = allCards.length;

    function getExternalFilterValue(attrName, fallback) {
      const value = browser.getAttribute(attrName);
      return value === null ? fallback : value;
    }

    function applyFilters() {
      const modelValue = modelFilter ? modelFilter.value : getExternalFilterValue('data-global-model-filter', '');
      const variantValue = variantFilter ? variantFilter.value : getExternalFilterValue('data-global-variant-filter', 'control');
      const resultValue = resultFilter ? resultFilter.value : getExternalFilterValue('data-global-result-filter', '');
      let visibleCardCount = 0;

      modelSections.forEach(function (section) {
        const cards = Array.from(section.querySelectorAll('.sample-card'));
        const sectionModel = section.getAttribute('data-model-group');
        let sectionHasVisibleCard = false;

        cards.forEach(function (card) {
          const cardModel = card.getAttribute('data-model');
          const cardVariant = card.getAttribute('data-variant') || 'control';
          const cardResult = card.getAttribute('data-result');
          const matchesModel = !modelValue || cardModel === modelValue;
          const matchesVariant = !variantValue || cardVariant === variantValue;
          const matchesResult = !resultValue || cardResult === resultValue;
          const hiddenByAssertion = card.classList.contains('hidden-by-assertion');
          const shouldShowCard = matchesModel && matchesVariant && matchesResult && !hiddenByAssertion;

          card.style.display = shouldShowCard ? '' : 'none';
          if (shouldShowCard) {
            sectionHasVisibleCard = true;
            visibleCardCount += 1;
          }
        });

        const sectionMatchesModel = !modelValue || sectionModel === modelValue;
        const shouldShowSection = sectionMatchesModel && sectionHasVisibleCard;
        section.style.display = shouldShowSection ? '' : 'none';
        section.toggleAttribute('hidden', !shouldShowSection);
      });

      if (noResultsMessage) {
        noResultsMessage.hidden = visibleCardCount > 0;
      }
      if (countEl) {
        countEl.textContent = 'Showing ' + visibleCardCount + ' of ' + totalCardCount + ' samples';
      }
      if (assertionCountEl) {
        assertionCountEl.textContent = 'Showing ' + visibleCardCount + ' of ' + totalCardCount + ' samples in this test case';
      }
    }

    function applyAssertionFilters() {
      const nameValue = nameFilter ? nameFilter.value : '';
      const statusValue = statusFilter ? statusFilter.value : '';

      allCards.forEach(function (card) {
        const assertionItems = Array.from(card.querySelectorAll('li[data-assertion-name][data-assertion-status]'));
        let matches = true;

        if (nameValue || statusValue) {
          matches = assertionItems.some(function (item) {
            const itemName = item.getAttribute('data-assertion-name') || '';
            const itemStatus = item.getAttribute('data-assertion-status') || '';
            const matchesName = !nameValue || itemName === nameValue;
            const matchesStatus = !statusValue || itemStatus === statusValue;
            return matchesName && matchesStatus;
          });
        }

        card.classList.toggle('hidden-by-assertion', !matches);
      });

      applyFilters();
    }

    browser.__applyExternalFilters = function (filters) {
      const nextFilters = filters || {};
      browser.setAttribute('data-global-model-filter', nextFilters.model || '');
      browser.setAttribute('data-global-variant-filter', Object.prototype.hasOwnProperty.call(nextFilters, 'variant') ? nextFilters.variant : 'control');
      browser.setAttribute('data-global-result-filter', nextFilters.result || '');
      applyAssertionFilters();
    };

    if (modelFilter) {
      modelFilter.addEventListener('change', applyFilters);
    }
    if (variantFilter) {
      variantFilter.addEventListener('change', applyFilters);
    }
    if (resultFilter) {
      resultFilter.addEventListener('change', applyFilters);
    }
    if (resetButton) {
      resetButton.addEventListener('click', function () {
        if (modelFilter) {
          modelFilter.value = '';
        }
        if (variantFilter) {
          variantFilter.value = 'control';
        }
        if (resultFilter) {
          resultFilter.value = '';
        }
        applyFilters();
      });
    }
    if (nameFilter) {
      nameFilter.addEventListener('change', applyAssertionFilters);
    }
    if (statusFilter) {
      statusFilter.addEventListener('change', applyAssertionFilters);
    }
    if (resetAssertionButton) {
      resetAssertionButton.addEventListener('click', function () {
        if (nameFilter) {
          nameFilter.value = '';
        }
        if (statusFilter) {
          statusFilter.value = '';
        }
        allCards.forEach(function (card) {
          card.classList.remove('hidden-by-assertion');
        });
        applyFilters();
      });
    }

    applyAssertionFilters();
  });
}
"""

DETAIL_PAGE_SCRIPT = DETAIL_BROWSER_SCRIPT + """
document.addEventListener('DOMContentLoaded', function () {
  async function fetchHtmlFragment(url) {
    const response = await fetch(url, { credentials: 'same-origin' });
    if (!response.ok) {
      throw new Error('Failed to load report fragment: ' + response.status);
    }
    return response.text();
  }

  initDetailBrowsers(document);

  document.addEventListener('click', async function (e) {
    var openBtn = e.target.closest('[data-opens-dialog]');
    if (openBtn) {
      var dialogId = openBtn.getAttribute('data-opens-dialog');
      var dialog = document.getElementById(dialogId);
      if (!dialog) return;
      var body = dialog.querySelector('.conversation-dialog-body');
      var src = openBtn.getAttribute('data-conversation-src');
      if (src && body && dialog.dataset.conversationLoaded !== 'true') {
        body.innerHTML = '<p>Loading conversation…</p>';
        try {
          body.innerHTML = await fetchHtmlFragment(src);
          dialog.dataset.conversationLoaded = 'true';
        } catch (error) {
          body.innerHTML = '<p>Unable to load conversation preview.</p>';
        }
      }
      dialog.showModal();
      return;
    }

    var closeBtn = e.target.closest('[data-closes-dialog]');
    if (closeBtn) {
      var closeDialogId = closeBtn.getAttribute('data-closes-dialog');
      var closeDialog = document.getElementById(closeDialogId);
      if (closeDialog) closeDialog.close();
    }
  });
});
"""

DETAIL_PAGE_TEMPLATE = """
<!DOCTYPE html>
<html lang=\"en\">
<head>
<meta charset=\"UTF-8\" />
<title>{{ test_name }} - {{ site_name }}</title>
<base href=\"../../\">
<style>{{ detail_page_style }}</style>
</head>
<body>
<main>
  <p class=\"breadcrumbs\"><a href=\"index.html#details-h2\">Back to main report</a></p>
  <h1>{{ test_name }}</h1>
  {{ body|safe }}
</main>
<script>{{ detail_page_script|safe }}</script>
</body>
</html>
"""

DETAIL_FRAGMENT_TEMPLATE = """
<section class=\"detail-fragment\" data-detail-browser>
  {% if test_data.prompt %}
  <details>
    <summary>Prompt</summary>
    <pre class=\"prompt-block\">{{ test_data.prompt|e }}</pre>
  </details>
  {% endif %}
  {% if test_data.assertion_filter_options %}
  <div class=\"filters assertion-filters\" role=\"region\" aria-label=\"Filters for assertions in {{ test_name }} test case\">
    <label>
      Assertion
      <select data-assertion-name-filter>
        <option value=\"\">All assertions</option>
        {% for assertion_name in test_data.assertion_filter_options %}
        <option value=\"{{ assertion_name }}\">{{ assertion_name }}</option>
        {% endfor %}
      </select>
    </label>
    <label>
      Assertion result
      <select data-assertion-status-filter>
        <option value=\"\">All results</option>
        <option value=\"pass\">Pass</option>
        <option value=\"fail\">Fail</option>
        <option value=\"na\">Not applicable</option>
      </select>
    </label>
    <button type=\"button\" data-assertion-reset-filters>Reset</button>
  </div>
  <p class=\"filters-summary\" data-assertion-filter-count aria-live=\"polite\" aria-atomic=\"true\"></p>
  {% endif %}
  {% for group in test_data.models %}
  <details data-model-group=\"{{ group.model_name }}\">
    <summary><{{ model_heading_tag }}>{{ model_display_names.get(group.model_name, group.model_name) }}</{{ model_heading_tag }}></summary>
    <p>Samples: {{ group.sample_count }} | Passes: {{ group.pass_count }}</p>
    <div class=\"samples\">
      {% for r in group.samples %}
      {% set vid = r.prompt_variant_id if r.prompt_variant_id is not none else 'control' %}
      <div class=\"sample-card\" data-model=\"{{ r.model_name }}\" data-result=\"{{ r.result }}\" data-variant=\"{{ vid }}\">
        <{{ sample_heading_tag }}>
          {% if report_include_generated_html_samples and r.generation_html_href %}
          <a href=\"{{ r.generation_html_href }}\">Sample {{ r.sample_index if r.sample_index is not none else loop.index0 }}{% if r.prompt_variant_kind == 'skill' %} &middot; Turn {{ (r.turn_index or 0) + 1 }}{% if r.turn_count_total %}/{{ r.turn_count_total }}{% endif %}{% if r.turn_id %} ({{ r.turn_id }}){% endif %}{% endif %} ({{ model_display_names.get(r.model_name, r.model_name) }})</a>
          {% else %}
          Sample {{ r.sample_index if r.sample_index is not none else loop.index0 }}{% if r.prompt_variant_kind == 'skill' %} &middot; Turn {{ (r.turn_index or 0) + 1 }}{% if r.turn_count_total %}/{{ r.turn_count_total }}{% endif %}{% if r.turn_id %} ({{ r.turn_id }}){% endif %}{% endif %} ({{ model_display_names.get(r.model_name, r.model_name) }})
          {% endif %}
        </{{ sample_heading_tag }}>
        <p>
          {% if r.prompt_variant_kind == 'skill' %}
            <strong>Skill:</strong> {{ prompt_variant_names.get(vid, vid) }}
            {% if r.turn_id %} &middot; <strong>Turn:</strong> {{ (r.turn_index or 0) + 1 }}{% if r.turn_count_total %}/{{ r.turn_count_total }}{% endif %} ({{ r.turn_id }}){% endif %}
          {% else %}
            <strong>Instruction set:</strong> {% if vid == 'control' %}Control{% else %}{{ prompt_variant_names.get(vid, vid) }}{% endif %}
          {% endif %}
        </p>
        <p><span class=\"badge-{{ 'pass' if r.result=='PASS' else 'fail' }}\">{{ r.result }}</span> | Latency {{ '%.2f'|format(r.generation.latency_s) }}s{% if r.generation.cached %} cached{% endif %}</p>
        <p>Axe WCAG: {{ r.axe.failure_count if r.axe else 'n/a' }}{% if r.axe and r.axe.best_practice_count > 0 %} | BP: {{ r.axe.best_practice_count }}{% endif %}{% if r.generation.cost_usd is not none %} | ${{ '%.4f'|format(r.generation.cost_usd) }}{% endif %}{% if r.generation.total_tokens is defined and r.generation.total_tokens is not none %} | Tokens: {{ '{:,}'.format(r.generation.total_tokens) }}{% if r.generation.tokens_in is defined and r.generation.tokens_out is defined and r.generation.tokens_in is not none and r.generation.tokens_out is not none %} ({{ '{:,}'.format(r.generation.tokens_in) }} in / {{ '{:,}'.format(r.generation.tokens_out) }} out){% endif %}{% endif %}</p>
        {% if r.screenshot_href %}
        <figure>
          <img src=\"{{ r.screenshot_href }}\" loading=\"lazy\" alt=\"Screenshot sample {{ r.sample_index }} for {{ r.test_name }} / {{ model_display_names.get(r.model_name, r.model_name) }}\" />
        </figure>
        {% endif %}
        {% if r.generation_conversation %}
        <button type=\"button\" class=\"conversation-btn\" data-opens-dialog=\"{{ r.conversation_dialog_id }}\" data-conversation-src=\"{{ r.generation_conversation.fragment_path }}\">Agent conversation ({{ r.generation_conversation.message_count }} messages{% if r.generation_conversation.entry_count is not none %}, {{ r.generation_conversation.entry_count }} entries{% endif %}{% if r.generation.agent_limit_error %}, limit: {{ r.generation.agent_limit_error }}{% endif %})</button>
        <dialog id=\"{{ r.conversation_dialog_id }}\" class=\"conversation-dialog\" aria-labelledby=\"{{ r.conversation_dialog_id }}-heading\">
          <div class=\"conversation-dialog-header\">
            <h2 id=\"{{ r.conversation_dialog_id }}-heading\">Agent conversation — Sample {{ r.sample_index if r.sample_index is not none else loop.index0 }} ({{ model_display_names.get(r.model_name, r.model_name) }})</h2>
            <button type=\"button\" class=\"conversation-dialog-close\" aria-label=\"Close\" data-closes-dialog=\"{{ r.conversation_dialog_id }}\">&#x2715;</button>
          </div>
          <div class=\"conversation-dialog-body\"></div>
        </dialog>
        {% endif %}
        <details>
          <summary>
            Assertions
            {% if r.test_function.status == 'fail' %}<span role=\"img\" aria-label=\"Fail\">❌</span>{% elif r.test_function.status == 'na' %}<span role=\"img\" aria-label=\"Not applicable\">➖</span>{% elif r.test_function.status == 'pass' %}<span role=\"img\" aria-label=\"Pass\">✅</span>{% endif %}
          </summary>
          <ul>
            {% for a in r.test_function.assertions %}
            <li data-assertion-name=\"{{ a.name|e }}\" data-assertion-status=\"{{ a.status|e }}\">
              {% if a.status == 'fail' %}<span role=\"img\" aria-label=\"Fail\">❌</span>:{% elif a.status == 'na' %}<span role=\"img\" aria-label=\"Not applicable\">➖</span>:{% elif a.status == 'pass' %}<span role=\"img\" aria-label=\"Pass\">✅</span>:{% endif %}
              {{ a.name|e }} ({{ a.type if a.type else 'R' }}): {{ a.status|e }}
              {% if a.message_parts %}
                {% if a.message_parts['title'] %} - <span>{{ a.message_parts['title']|e }}</span>{% else %} - {% endif %}
                <div class=\"assertion-message-block\">
                  <ul class=\"assertion-message-list\">
                    {% for item in a.message_parts['items'] %}
                    <li>{{ item|e }}</li>
                    {% endfor %}
                  </ul>
                </div>
              {% elif a.message %}
                - {{ a.message|e }}
              {% endif %}
            </li>
            {% endfor %}
          </ul>
        </details>
        {% if r.axe %}
          {% if r.axe.failure_count > 0 %}
          <details>
            <summary>Axe WCAG Failures ({{ r.axe.failure_count }}) <span role=\"img\" aria-label=\"Fail\">❌</span></summary>
            <ul>{% for v in r.axe.failures %}<li>({{ v.nodes|length }}x) - <strong>{{ v.id|e }}</strong> ({{ v.impact|e }}): {{ v.description|e }}</li>{% endfor %}</ul>
          </details>
          {% else %}
          <details>
            <summary>Axe WCAG Failures (0) <span role=\"img\" aria-label=\"Pass\">✅</span></summary>
            <p>No WCAG violations detected by axe-core.</p>
          </details>
          {% endif %}
          {% if r.axe.best_practice_count > 0 %}
          <details>
            <summary>Axe Best Practice Issues ({{ r.axe.best_practice_count }}) <span role=\"img\" aria-label=\"Warning\">⚠️</span></summary>
            <ul>{% for v in r.axe.best_practice_failures %}<li><strong>{{ v.id|e }}</strong> ({{ v.impact|e }}): {{ v.description|e }} <em>(Best Practice - does not affect pass/fail)</em></li>{% endfor %}</ul>
          </details>
          {% else %}
          <details>
            <summary>Axe Best Practice Issues (0) <span role=\"img\" aria-label=\"Pass\">✅</span></summary>
            <p>No best practice issues detected by axe-core.</p>
          </details>
          {% endif %}
        {% endif %}
      </div>
      {% endfor %}
    </div>
  </details>
  {% endfor %}
</section>
"""

CONVERSATION_FRAGMENT_TEMPLATE = """
{% if turns %}
<div class=\"transcript-turns\">
  {% for turn in turns %}
  <div class=\"transcript-turn transcript-turn-{{ turn.role }}\">
    <p class=\"transcript-turn-header\">{{ turn.role_label }}</p>
    {% for msg in turn.messages %}
      {% if msg.label == 'Prompt' %}
      <pre class=\"prompt-block transcript-turn-prompt\">{{ msg.content|e }}</pre>
      {% else %}
      <p class=\"transcript-turn-msg\"><span class=\"transcript-turn-msg-label\">{{ msg.label }}:</span> {{ msg.content|e }}</p>
      {% endif %}
    {% endfor %}
    {% if turn.tool_calls %}
    <p class=\"transcript-tool-list\">{% for tc in turn.tool_calls %}{{ tc|e }}{% if not loop.last %}<br>{% endif %}{% endfor %}</p>
    {% endif %}
  </div>
  {% endfor %}
</div>
{% else %}
<p><em>No transcript preview available.</em></p>
{% endif %}
"""