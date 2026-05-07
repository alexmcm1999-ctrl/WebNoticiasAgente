const digest = window.DIGEST_DATA || { topics: [], errors: [], generatedAt: null };

const translations = {
  es: {
    eyebrow: "Radar diario",
    title: "IA y mercado energetico",
    language: "Idioma",
    generatedAt: "Actualizado",
    dateUnavailable: "Fecha no disponible",
    sourceHealthOk: "Fuentes OK",
    sourceHealthWarnings: "aviso(s)",
    noModel: "sin modelo",
    search: "Buscar",
    searchPlaceholder: "Fuente, tema o titular",
    filterAll: "Todas las fuentes",
    filterForum: "Solo foros",
    filterRss: "Noticias / RSS",
    filterPaper: "Papers",
    noTheme: "sin tema dominante",
    noResultsTitle: "No hay resultados con este filtro.",
    noResultsBody: "Prueba a quitar el filtro o actualiza el informe.",
    errorTitle: "Avisos de fuentes",
    sourceTypeForum: "Foro",
    sourceTypeRss: "Medio",
    sourceTypePaper: "Paper",
    sourceTypeOther: "Fuente",
    signal: "Senal",
    viewDiscussion: "Ver conversacion",
    noSummary: "Sin resumen adicional disponible.",
    summaryThemesLabel: "Temas detectados",
  },
  en: {
    eyebrow: "Daily radar",
    title: "AI and energy market",
    language: "Language",
    generatedAt: "Updated",
    dateUnavailable: "Date unavailable",
    sourceHealthOk: "Sources OK",
    sourceHealthWarnings: "warning(s)",
    noModel: "no model",
    search: "Search",
    searchPlaceholder: "Source, theme or headline",
    filterAll: "All sources",
    filterForum: "Forums only",
    filterRss: "News / RSS",
    filterPaper: "Papers",
    noTheme: "no dominant theme",
    noResultsTitle: "No results for this filter.",
    noResultsBody: "Try removing the filter or refresh the digest.",
    errorTitle: "Source notices",
    sourceTypeForum: "Forum",
    sourceTypeRss: "Outlet",
    sourceTypePaper: "Paper",
    sourceTypeOther: "Source",
    signal: "Signal",
    viewDiscussion: "View discussion",
    noSummary: "No additional summary available.",
    summaryThemesLabel: "Detected themes",
  },
};

let activeTopicId = digest.topics[0]?.id || "ai";
let currentLanguage = localStorage.getItem("digestLanguage") || "es";

const generatedAt = document.querySelector("#generatedAt");
const sourceHealth = document.querySelector("#sourceHealth");
const summary = document.querySelector("#summary");
const feed = document.querySelector("#feed");
const errors = document.querySelector("#errors");
const searchInput = document.querySelector("#searchInput");
const sourceType = document.querySelector("#sourceType");
const languageSelect = document.querySelector("#languageSelect");

function t(key) {
  return translations[currentLanguage]?.[key] || translations.es[key] || key;
}

function formatDate(value) {
  if (!value) return t("dateUnavailable");
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(currentLanguage === "es" ? "es-ES" : "en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function labelForSourceType(type) {
  const labels = {
    forum: t("sourceTypeForum"),
    rss: t("sourceTypeRss"),
    paper: t("sourceTypePaper"),
  };
  return labels[type] || t("sourceTypeOther");
}

function currentTopic() {
  return digest.topics.find((topic) => topic.id === activeTopicId) || digest.topics[0];
}

function localizedText(item, field) {
  if (currentLanguage === "es") {
    const translated = item.translations?.es?.[field];
    if (translated) return translated;
  }
  return item[field] || "";
}

function applyStaticTranslations() {
  document.documentElement.lang = currentLanguage;
  document.title = t("title");
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  searchInput.placeholder = t("searchPlaceholder");
  document.querySelector('[value="all"]').textContent = t("filterAll");
  document.querySelector('[value="forum"]').textContent = t("filterForum");
  document.querySelector('[value="rss"]').textContent = t("filterRss");
  document.querySelector('[value="paper"]').textContent = t("filterPaper");
}

function renderStatus() {
  generatedAt.textContent = `${t("generatedAt")}: ${formatDate(digest.generatedAt)}`;
  const errorCount = digest.errors?.length || 0;
  const model = currentTopic()?.summary?.model || t("noModel");
  sourceHealth.textContent = errorCount === 0 ? `${t("sourceHealthOk")} | ${model}` : `${errorCount} ${t("sourceHealthWarnings")} | ${model}`;
}

function renderTabs() {
  document.querySelectorAll(".tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.topic === activeTopicId);
    button.textContent = currentLanguage === "es" ? button.dataset.topicLabelEs : button.dataset.topicLabelEn;
    button.onclick = () => {
      activeTopicId = button.dataset.topic;
      render();
    };
  });
}

function renderSummary(topic) {
  const topicSummary = topic.summary || {};
  const bullets = (topicSummary.bullets || []).map((bullet) => `<li>${escapeHtml(bullet)}</li>`).join("");
  const themes = (topicSummary.themes || []).map((theme) => `<span class="theme">${escapeHtml(theme)}</span>`).join("");

  summary.innerHTML = `
    <article class="summary-copy">
      <h2>${escapeHtml(topicSummary.headline || topic.label)}</h2>
      <ul>${bullets}</ul>
    </article>
    <aside class="theme-list" aria-label="${escapeHtml(t("summaryThemesLabel"))}">
      ${themes || `<span class="theme">${escapeHtml(t("noTheme"))}</span>`}
    </aside>
  `;
}

function renderFeed(topic) {
  const query = searchInput.value.trim().toLowerCase();
  const type = sourceType.value;
  const items = (topic.items || []).filter((item) => {
    const matchesType = type === "all" || item.sourceType === type;
    const haystack = `${localizedText(item, "title")} ${item.source} ${localizedText(item, "summary")}`.toLowerCase();
    const matchesQuery = !query || haystack.includes(query);
    return matchesType && matchesQuery;
  });

  if (!items.length) {
    feed.innerHTML = `<article class="item"><h3>${escapeHtml(t("noResultsTitle"))}</h3><p>${escapeHtml(t("noResultsBody"))}</p></article>`;
    return;
  }

  feed.innerHTML = items
    .map(
      (item) => `
      <article class="item">
        <header>
          <span class="badge">${labelForSourceType(item.sourceType)}</span>
          <span class="meta">${escapeHtml(item.source)}</span>
        </header>
        <h3><a href="${escapeAttribute(item.url)}" target="_blank" rel="noreferrer">${escapeHtml(localizedText(item, "title"))}</a></h3>
        <p>${escapeHtml(localizedText(item, "summary") || t("noSummary"))}</p>
        <div class="score">
          <span>${formatDate(item.published)}</span>
          <span>${t("signal")} ${Number(item.score || 0).toFixed(1)}</span>
        </div>
        ${item.commentsUrl ? `<a class="meta" href="${escapeAttribute(item.commentsUrl)}" target="_blank" rel="noreferrer">${escapeHtml(t("viewDiscussion"))}</a>` : ""}
      </article>
    `,
    )
    .join("");
}

function renderErrors() {
  if (!digest.errors?.length) {
    errors.hidden = true;
    return;
  }
  errors.hidden = false;
  errors.innerHTML = `<strong>${escapeHtml(t("errorTitle"))}</strong><br>${digest.errors.map(escapeHtml).join("<br>")}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttribute(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}

function render() {
  applyStaticTranslations();
  renderTabs();
  const topic = currentTopic();
  renderStatus();
  renderSummary(topic);
  renderFeed(topic);
  renderErrors();
}

searchInput.addEventListener("input", render);
sourceType.addEventListener("change", render);
languageSelect.value = currentLanguage;
languageSelect.addEventListener("change", () => {
  currentLanguage = languageSelect.value || "es";
  localStorage.setItem("digestLanguage", currentLanguage);
  render();
});

render();
