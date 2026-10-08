console.log("ZAP Imóveis v4: coletor simplificado com maestro carregado");

const WORKER = globalThis.ZAP_V4_WORKER || {};
const CLASSIFICADORES = globalThis.ZAP_V4_CLASSIFICADORES;
const WORKER_ID = WORKER.id || "worker1";
const STORAGE_KEY = `zap_v4_maestro_${WORKER_ID}`;
const CONFIG = {
  maxPaginas: 50,
  esperaNormalMinMs: 0, esperaNormalMaxMs: 0,
  backoffCadaPaginas: 50, backoffMinMs: 10_000, backoffMaxMs: 20_000,
  esperaErroMinMs: 45_000, esperaErroMaxMs: 75_000,
  esperaCargaMs: 3_000, maxScrolls: 24, maxReloads: 4,
  esperaFilaMs: 30_000
};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const sorteio = (a, b) => Math.floor(Math.random() * (b - a + 1)) + a;
const texto = (el) => (el?.innerText || el?.textContent || "").replace(/\s+/g, " ").trim();
const semAcentos = CLASSIFICADORES.semAcentos;
const unico = (xs) => [...new Set(xs.filter(Boolean))];
const inteiro = (v) => { const m = String(v || "").match(/\d+/); return m ? Number(m[0]) : null; };
const dinheiro = (v) => {
  const n = Number(String(v || "").replace(/[^\d,.-]/g, "").replace(/\./g, "").replace(",", "."));
  return Number.isFinite(n) ? n : null;
};

function normalizarUrl(v) {
  try {
    const u = new URL(v, location.origin); u.hash = "";
    ["source", "utm_source", "utm_medium", "utm_campaign", "utm_content"].forEach((k) => u.searchParams.delete(k));
    return u.href;
  } catch { return v || ""; }
}

function estadoInicial() {
  return {
    rodando: false, worker: WORKER_ID, tarefaAtual: null, paginaAtual: 1,
    maxPaginas: CONFIG.maxPaginas, totalCards: 0, paginasConcluidas: [],
    assinaturaAnterior: null, urlSolicitada: null, recarregamentos: 0,
    ultimoStatus: "aguardando início", ultimaAtualizacao: new Date().toISOString()
  };
}
function obterEstado() {
  try { return { ...estadoInicial(), ...JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}") }; }
  catch { return estadoInicial(); }
}
function guardar(e) {
  e.ultimaAtualizacao = new Date().toISOString();
  localStorage.setItem(STORAGE_KEY, JSON.stringify(e));
}
function servidor(endpoint, method = "GET", payload = null) {
  return new Promise((resolve, reject) => chrome.runtime.sendMessage(
    { tipo: "fetch_servidor", endpoint, method, payload }, (r) => {
      if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
      if (!r?.ok) return reject(new Error(r?.data?.erro || r?.erro || `Servidor HTTP ${r?.status || 0}`));
      resolve(r.data);
    }
  ));
}
async function checkpoint(e) {
  guardar(e);
  try { await servidor(`/worker/${WORKER_ID}/checkpoint`, "POST", e); }
  catch (err) { console.warn("Checkpoint ficou salvo localmente:", err); }
}

function tarefa(e) { return e.tarefaAtual || null; }
function urlBusca(pagina = 1, e = obterEstado()) {
  const atual = tarefa(e);
  if (!atual?.url_base) throw new Error("Worker sem tarefa reservada.");
  const u = new URL(atual.url_base);
  u.searchParams.set("tipos", atual.tipo_id);
  if (pagina > 1) u.searchParams.set("pagina", String(pagina));
  else u.searchParams.delete("pagina");
  return u.href;
}
function paginaPertenceATarefa(e) {
  const atual = tarefa(e);
  if (!atual) return false;
  try {
    const aberta = new URL(location.href);
    const esperada = new URL(atual.url_base);
    const tipos = (aberta.searchParams.get("tipos") || "").split(",").filter(Boolean);
    const esperados = atual.tipo_id.split(",").filter(Boolean);
    return aberta.hostname.endsWith("zapimoveis.com.br") &&
      aberta.pathname.replace(/\/+$/, "") === esperada.pathname.replace(/\/+$/, "") &&
      tipos.length === esperados.length && esperados.every((tipo) => tipos.includes(tipo));
  } catch { return false; }
}

function ehAreaDeRecomendacao(elemento) {
  if (!elemento) return false;
  if (elemento.closest?.('[data-testid^="recommendation-item-"]')) return true;
  const link = elemento.matches?.("a[href]") ? elemento : elemento.querySelector?.("a[href]");
  if (link) {
    try {
      if (CLASSIFICADORES.urlEhRecomendacao(link.href, location.origin)) return true;
    } catch { /* URL inválida é descartada mais tarde. */ }
  }
  const carousel = elemento.closest?.('[data-scope="carousel"][data-part="root"]');
  if (carousel && /mais opcoes para voce na mesma regiao/i.test(semAcentos(texto(carousel)))) return true;
  return false;
}

function paginaSemResultados() {
  return CLASSIFICADORES.textoIndicaSemResultados(texto(document.body));
}

function totalAnunciosPagina() {
  // Usa apenas o total explícito em títulos, evitando preços e contagens de recomendações.
  for (const el of document.querySelectorAll('h1, h2, [data-testid="listing-count"], [data-cy="rp-resultCount"]')) {
    const t = texto(el);
    const m = t.match(/(?:^|\s)(\d[\d.\s]*)\s+(?:imóveis|imoveis|anúncios|anuncios)\b/i);
    if (m) return Number(m[1].replace(/\D/g, ""));
  }
  return null;
}

function detectarIncidente() {
  const titulo = semAcentos(document.title);
  const corpo = semAcentos(texto(document.body));
  const s = `${titulo} ${corpo.slice(0, 7000)}`;
  if (/erro\s*404|pagina nao encontrada|nao encontramos essa pagina|esta pagina nao existe|nao conseguimos encontrar a pagina solicitada/.test(s)) return "PAGINA_NAO_ENCONTRADA";
  if (/cloudflare|just a moment|checking your browser|verifica.{0,8}humana|access denied|captcha/.test(s)) return "CLOUDFLARE";
  if (/http\s*505|http version not supported|erro\s*505/.test(s)) return "HTTP_505";
  if (/http\s*5(?:00|02|03|04)|erro\s*5(?:00|02|03|04)|erro interno do servidor|service unavailable|bad gateway|gateway timeout/.test(s)) return "HTTP_5XX";
  return null;
}

async function incidente(tipo, e, detalhe = "") {
  const atual = tarefa(e) || {};
  const evento = {
    tipo, detalhe, horario: new Date().toISOString(), url: location.href,
    worker: WORKER_ID, tarefa_id: atual.id, municipio: atual.municipio,
    uf: atual.uf, tipo_id: atual.tipo_id, pagina: e.paginaAtual
  };
  console.warn("Incidente ZAP v4", evento);
  try { await servidor("/incidente", "POST", evento); } catch (err) { console.warn(err); }
}

async function obterProximaTarefa(e) {
  const resposta = await servidor(`/worker/${WORKER_ID}/proxima-tarefa`, "POST", {});
  if (resposta.tarefa) {
    e.tarefaAtual = resposta.tarefa;
    e.paginaAtual = Math.max(1, Number(resposta.tarefa.pagina_atual || 1));
    e.paginasConcluidas = [];
    e.assinaturaAnterior = null;
    e.urlSolicitada = null;
    e.recarregamentos = 0;
    e.ultimoStatus = `${resposta.retomada ? "retomando" : "iniciando"} ${resposta.tarefa.municipio}/${resposta.tarefa.uf} · ${resposta.tarefa.tipo_rotulo}`;
    await checkpoint(e);
    return "TAREFA";
  }
  if (resposta.fila_concluida) {
    e.rodando = false; e.tarefaAtual = null;
    e.ultimoStatus = "fila concluída: não há mais municípios e tipos pendentes";
    await checkpoint(e);
    return "FIM";
  }
  e.ultimoStatus = "fila temporariamente sem tarefa disponível; aguardando";
  await checkpoint(e);
  return "AGUARDAR";
}

async function concluirTarefa(e, status, detalhe) {
  const atual = tarefa(e);
  if (!atual) return;
  await servidor(`/worker/${WORKER_ID}/tarefa/${atual.id}/concluir`, "POST", {
    status, pagina: e.paginaAtual, detalhe
  });
  e.tarefaAtual = null; e.paginaAtual = 1; e.paginasConcluidas = [];
  e.assinaturaAnterior = null; e.recarregamentos = 0;
  e.urlSolicitada = null;
  e.ultimoStatus = detalhe;
  await checkpoint(e);
}

async function validarReserva(e) {
  const atual = tarefa(e);
  if (!atual) return false;
  try {
    await servidor(`/worker/${WORKER_ID}/tarefa/${atual.id}/heartbeat`, "POST", { pagina: e.paginaAtual });
    return true;
  } catch {
    e.tarefaAtual = null; e.paginaAtual = 1; e.paginasConcluidas = [];
    e.assinaturaAnterior = null; e.urlSolicitada = null; e.recarregamentos = 0;
    e.ultimoStatus = "reserva expirada ou transferida; solicitando nova tarefa";
    await checkpoint(e);
    return false;
  }
}

async function falharTarefa(e, detalhe) {
  const atual = tarefa(e);
  if (!atual) return;
  await servidor(`/worker/${WORKER_ID}/tarefa/${atual.id}/falhar`, "POST", {
    pagina: e.paginaAtual, detalhe
  });
  e.tarefaAtual = null; e.paginaAtual = 1; e.paginasConcluidas = [];
  e.assinaturaAnterior = null; e.urlSolicitada = null; e.recarregamentos = 0;
  e.ultimoStatus = `tarefa devolvida ao maestro: ${detalhe}`;
  await checkpoint(e);
}

async function seguirParaOutraTarefa(e, status, detalhe) {
  const pausarNoLimite = status === "CONCLUIDA" && e.paginaAtual % CONFIG.backoffCadaPaginas === 0;
  await concluirTarefa(e, status, detalhe);
  if (pausarNoLimite) {
    await sleep(sorteio(CONFIG.backoffMinMs, CONFIG.backoffMaxMs));
  }
  const resultado = await obterProximaTarefa(e);
  if (resultado === "TAREFA") {
    await sleep(sorteio(CONFIG.esperaNormalMinMs, CONFIG.esperaNormalMaxMs));
    location.assign(urlBusca(1, e));
  } else if (resultado === "AGUARDAR") {
    setTimeout(() => executar(), CONFIG.esperaFilaMs);
  }
}

async function falharESeguir(e, detalhe) {
  await falharTarefa(e, detalhe);
  const resultado = await obterProximaTarefa(e);
  if (resultado === "TAREFA") location.assign(urlBusca(1, e));
  else if (resultado === "AGUARDAR") setTimeout(() => executar(), CONFIG.esperaFilaMs);
}

async function recarregarOuFalhar(tipo, e) {
  e.recarregamentos = (e.recarregamentos || 0) + 1;
  await incidente(tipo, e, `tentativa ${e.recarregamentos}/${CONFIG.maxReloads}`);
  if (e.recarregamentos > CONFIG.maxReloads) {
    return falharESeguir(e, `${tipo} após ${CONFIG.maxReloads} recargas`);
  }
  e.ultimoStatus = `${tipo}: recarga ${e.recarregamentos}/${CONFIG.maxReloads} após 45–75 s`;
  await checkpoint(e);
  await sleep(sorteio(CONFIG.esperaErroMinMs, CONFIG.esperaErroMaxMs));
  location.reload();
}

function cardsPrincipais() {
  const seletores = [
    'li[data-cy="rp-property-cd"]',
    '[data-testid="property-card"]',
    'article:has(a[href*="/imovel/"])',
    'a[data-ds-component="DS-Card"][href*="/imovel/"]'
  ];
  for (const seletor of seletores) {
    const cards = [...document.querySelectorAll(seletor)].filter((card) => !ehAreaDeRecomendacao(card));
    if (cards.length) return cards;
  }
  return unico([...document.querySelectorAll('a[href*="/imovel/"]')]
    .filter((a) => !ehAreaDeRecomendacao(a))
    .map((a) => a.closest('li, article, [data-cy="rp-property-cd"], [data-testid="property-card"]'))
    .filter(Boolean));
}

async function carregarCards() {
  let anterior = -1, estavel = 0;
  for (let i = 0; i < CONFIG.maxScrolls && estavel < 4; i++) {
    window.scrollBy({ top: Math.max(650, innerHeight * .8), behavior: "smooth" });
    await sleep(650);
    const atual = cardsPrincipais().length;
    estavel = atual === anterior ? estavel + 1 : 0; anterior = atual;
  }
  window.scrollTo({ top: 0, behavior: "smooth" }); await sleep(900);
}

const valor = (card, seletor) => texto(card.querySelector(seletor));
function extrairCard(card, pagina, posicao, e) {
  if (ehAreaDeRecomendacao(card)) return null;
  const atual = tarefa(e);
  const a = card.matches?.('a[href*="/imovel/"]') ? card : card.querySelector('a[href*="/imovel/"]');
  if (!a?.href || ehAreaDeRecomendacao(a)) return null;
  const original = a.href, url = normalizarUrl(original), titulo = a.title || valor(card, '[data-cy="rp-cardProperty-location-txt"]');
  const blocoPreco = valor(card, '[data-cy="rp-cardProperty-price-txt"]');
  const precoTxt = blocoPreco.match(/R\$\s*[\d.]+(?:,\d{2})?/)?.[0] || null;
  const cond = blocoPreco.match(/Cond\.?(?:omínio)?\s*(R\$\s*[\d.]+(?:,\d{2})?|não informado)/i)?.[1] || null;
  const iptu = blocoPreco.match(/IPTU\s*(R\$\s*[\d.]+(?:,\d{2})?|não informado)/i)?.[1] || null;
  const area = inteiro(valor(card, '[data-cy="rp-cardProperty-propertyArea-txt"]')), preco = dinheiro(precoTxt);
  const local = valor(card, '[data-cy="rp-cardProperty-location-txt"]');
  const partes = local.split(",").map((x) => x.trim()).filter(Boolean);
  const icon = card.querySelector('[data-testid="verified-advertiser-icon"]');
  const anunciante = icon?.closest("div")?.querySelector("span[title], span");
  const badges = unico([...card.querySelectorAll('[data-cy="rp-cardProperty-tag-txt"], [class*="badge"]')].map(texto));
  const duplicado = valor(card, '[data-cy="listing-card-deduplicated-button"]');
  const fotos = unico([...card.querySelectorAll("img")].flatMap((img) => [img.currentSrc, img.src,
    ...(img.srcset || "").split(",").map((x) => x.trim().split(/\s+/)[0])]).map(normalizarUrl));
  return {
    id_anuncio: url.match(/id-(\d+)/)?.[1] || null, url, url_original: original, titulo,
    tipo_imovel: (url.match(/(?:venda|aluguel)-([^-]+)/)?.[1] || "").replace(/-/g, " ") || null,
    tipo_solicitado: atual.tipo_id, operacao: /\/aluguel-|\/aluguel\//.test(url) ? "Aluguel" : "Venda",
    area_m2: area, quartos: inteiro(valor(card, '[data-cy="rp-cardProperty-bedroomQuantity-txt"]')),
    banheiros: inteiro(valor(card, '[data-cy="rp-cardProperty-bathroomQuantity-txt"]')),
    vagas: inteiro(valor(card, '[data-cy="rp-cardProperty-parkingSpacesQuantity-txt"]')),
    preco, preco_texto: precoTxt, preco_m2: preco && area ? Math.round(preco / area * 100) / 100 : null,
    condominio: cond && !/não informado/i.test(cond) ? dinheiro(cond) : null,
    condominio_informado: !!cond && !/não informado/i.test(cond),
    iptu: iptu && !/não informado/i.test(iptu) ? dinheiro(iptu) : null,
    iptu_informado: !!iptu && !/não informado/i.test(iptu),
    endereco: valor(card, '[data-cy="rp-cardProperty-street-txt"]') || null,
    bairro: partes.length >= 2 ? partes.at(-2) : partes[0] || null,
    cidade: atual.municipio, estado: atual.uf, localizacao_card: local || null,
    anunciante: texto(anunciante) || anunciante?.title || null, anunciante_verificado: !!icon,
    destaque: badges.join(" | ") || null, tipo_destaque_interno: card.getAttribute("data-type") || null,
    visualizado: badges.some((x) => /visualizado/i.test(x)),
    anuncios_mesmo_imovel: inteiro(duplicado), texto_duplicidade: duplicado || null,
    fotos_quantidade_carregada: fotos.length, fotos_urls: fotos,
    fotos_alt: unico([...card.querySelectorAll("img[alt]")].map((img) => img.alt)),
    pagina, posicao_pagina: posicao + 1, worker: WORKER_ID, tarefa_id: atual.id,
    busca: atual.tipo_id, grupo_tipos: atual.tipo_rotulo,
    coletado_em: new Date().toISOString(), fonte: "card_zap_v4_maestro"
  };
}

function assinatura(itens) {
  return itens.map((item) => item.id_anuncio || item.url).filter(Boolean).sort().join("|");
}
function proximaPagina() {
  const candidatos = [...document.querySelectorAll('a[href][aria-label], a[data-testid*="next" i][href], nav a[href]')];
  const a = candidatos.find((el) => !ehAreaDeRecomendacao(el) &&
    /proxima pagina|próxima página|next page/i.test(`${el.getAttribute("aria-label") || ""} ${texto(el)}`));
  return a?.href && a.getAttribute("aria-disabled") !== "true" ? normalizarUrl(a.href) : null;
}

async function executar() {
  if (window.__zapV4Executando) return;
  window.__zapV4Executando = true;
  try {
    const e = obterEstado();
    if (!e.rodando) return;
    if (!tarefa(e)) {
      const resultado = await obterProximaTarefa(e);
      if (resultado === "FIM") return;
      if (resultado === "AGUARDAR") { setTimeout(() => executar(), CONFIG.esperaFilaMs); return; }
    }
    if (!await validarReserva(e)) {
      setTimeout(() => executar(), 1_000);
      return;
    }
    const atual = tarefa(e);
    if (location.pathname.includes("/imovel/")) {
      await incidente("ENTRADA_INDEVIDA_NO_ANUNCIO", e);
      return seguirParaOutraTarefa(e, "ERRO_PERMANENTE", "página de anúncio aberta indevidamente");
    }
    if (!paginaPertenceATarefa(e)) {
      if (e.urlSolicitada) {
        await sleep(2_000);
        if (paginaSemResultados()) {
          return seguirParaOutraTarefa(e, "SEM_ANUNCIOS", `sem anúncios correspondentes em ${atual.municipio}/${atual.uf}`);
        }
        const falhaRedirecionada = detectarIncidente();
        if (falhaRedirecionada === "PAGINA_NAO_ENCONTRADA") {
          await incidente(falhaRedirecionada, e, "a URL da tarefa redirecionou para página inexistente");
          return seguirParaOutraTarefa(e, "PAGINA_NAO_ENCONTRADA", `página não encontrada para ${atual.municipio}/${atual.uf}`);
        }
        if (falhaRedirecionada) return recarregarOuFalhar(falhaRedirecionada, e);
        return falharESeguir(e, `URL redirecionada ou busca não reconhecida: ${location.href}`);
      }
      e.urlSolicitada = urlBusca(e.paginaAtual, e);
      e.ultimoStatus = `indo para ${atual.municipio}/${atual.uf} · ${atual.tipo_rotulo} · página ${e.paginaAtual}`;
      await checkpoint(e); location.assign(e.urlSolicitada); return;
    }
    e.urlSolicitada = null;
    await sleep(CONFIG.esperaCargaMs);

    if (paginaSemResultados()) {
      return seguirParaOutraTarefa(e, "SEM_ANUNCIOS", `sem anúncios correspondentes em ${atual.municipio}/${atual.uf}`);
    }
    const falha = detectarIncidente();
    if (falha === "PAGINA_NAO_ENCONTRADA") {
      await incidente(falha, e);
      return seguirParaOutraTarefa(e, "PAGINA_NAO_ENCONTRADA", `página não encontrada para ${atual.municipio}/${atual.uf}`);
    }
    if (falha) return recarregarOuFalhar(falha, e);

    if (atual.tipo_rotulo === "Avaliar total de anúncios") {
      const total = totalAnunciosPagina();
      if (total === null) return recarregarOuFalhar("TOTAL_ANUNCIOS_NAO_IDENTIFICADO", e);
      const decisao = await servidor(`/worker/${WORKER_ID}/tarefa/${atual.id}/avaliar-total`, "POST", { total });
      if (decisao.dividida) {
        e.tarefaAtual = null; e.urlSolicitada = null;
        await checkpoint(e);
        const resultado = await obterProximaTarefa(e);
        if (resultado === "TAREFA") location.assign(urlBusca(1, e));
        else if (resultado === "AGUARDAR") setTimeout(() => executar(), CONFIG.esperaFilaMs);
        return;
      }
      atual.tipo_rotulo = "Busca única por total";
      await checkpoint(e);
    }
    // Os cards presentes são coletados sem rolagem automática.
    if (paginaSemResultados()) {
      return seguirParaOutraTarefa(e, "SEM_ANUNCIOS", `sem anúncios correspondentes em ${atual.municipio}/${atual.uf}`);
    }
    const itens = cardsPrincipais().map((card, i) => extrairCard(card, e.paginaAtual, i, e)).filter(Boolean);
    if (!itens.length) return recarregarOuFalhar("PAGINA_SEM_CARDS_E_SEM_MENSAGEM", e);

    const atualAssinatura = assinatura(itens);
    if (e.assinaturaAnterior && atualAssinatura === e.assinaturaAnterior) {
      await incidente("PAGINA_REPETIDA", e, "mesmos anúncios da página anterior");
      return seguirParaOutraTarefa(e, "CONCLUIDA", "paginação encerrada: página repetida evitou loop");
    }
    if ((e.paginasConcluidas || []).includes(e.paginaAtual)) {
      return seguirParaOutraTarefa(e, "CONCLUIDA", "paginação encerrada: página já processada evitou loop");
    }

    const resposta = await servidor("/dados-lista", "POST", {
      worker: WORKER_ID, tarefa_id: atual.id, municipio: atual.municipio, uf: atual.uf,
      tipo_id: atual.tipo_id, busca: atual.tipo_id, grupo_tipos: atual.tipo_rotulo,
      pagina: e.paginaAtual, url_pagina: location.href, itens
    });
    e.totalCards = resposta.total_worker ?? e.totalCards + itens.length;
    e.recarregamentos = 0; e.assinaturaAnterior = atualAssinatura;
    e.paginasConcluidas = unico([...(e.paginasConcluidas || []), e.paginaAtual]);
    e.ultimoStatus = `${atual.municipio}/${atual.uf} · ${atual.tipo_rotulo} · página ${e.paginaAtual}: ${itens.length} cards`;
    await checkpoint(e);

    const proxima = proximaPagina();
    const limitePaginas = atual.tipo_rotulo === "Busca única por total" ? 100 : CONFIG.maxPaginas;
    if (!proxima || e.paginaAtual >= limitePaginas) {
      const motivo = e.paginaAtual >= limitePaginas ? `limite de ${limitePaginas} páginas` : "fim da paginação";
      return seguirParaOutraTarefa(e, "CONCLUIDA", `${atual.municipio}/${atual.uf} · ${atual.tipo_rotulo}: ${motivo}`);
    }
    const numeroAtual = e.paginaAtual;
    e.paginaAtual += 1;
    const aplicarBackoff = numeroAtual % CONFIG.backoffCadaPaginas === 0;
    e.ultimoStatus = aplicarBackoff ? `pausa de segurança; próxima página ${e.paginaAtual}` : `indo para a página ${e.paginaAtual}`;
    await checkpoint(e);
    const espera = aplicarBackoff ? sorteio(CONFIG.backoffMinMs, CONFIG.backoffMaxMs) : sorteio(CONFIG.esperaNormalMinMs, CONFIG.esperaNormalMaxMs);
    await sleep(espera); location.assign(proxima);
  } catch (err) {
    const e = obterEstado();
    await incidente("ERRO_JAVASCRIPT_OU_SERVIDOR", e, String(err?.stack || err));
    if (tarefa(e)) {
      try { await falharTarefa(e, String(err?.message || err)); }
      catch {
        e.tarefaAtual = null; e.paginaAtual = 1; e.paginasConcluidas = [];
      }
    }
    e.ultimoStatus = `erro: ${String(err?.message || err)}`; await checkpoint(e);
    if (e.rodando) setTimeout(() => executar(), CONFIG.esperaFilaMs);
  } finally {
    window.__zapV4Executando = false;
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    let e = obterEstado();
    if (msg.action === "start") {
      const remoto = await servidor(`/worker/${WORKER_ID}/checkpoint`);
      const base = Object.keys(remoto.checkpoint || {}).length ? remoto.checkpoint : estadoInicial();
      e = { ...estadoInicial(), ...base, urlSolicitada: null, rodando: true, ultimoStatus: "coleta iniciada/retomada" };
      await checkpoint(e); sendResponse({ ok: true, estado: e }); executar(); return;
    }
    if (msg.action === "stop") {
      e.rodando = false; e.ultimoStatus = "pausada pelo usuário"; await checkpoint(e);
    }
    if (msg.action === "reset") {
      await servidor(`/worker/${WORKER_ID}/liberar-tarefa`, "POST", { tarefa_id: e.tarefaAtual?.id }).catch(() => null);
      e = estadoInicial(); await checkpoint(e);
    }
    if (msg.action === "status") {
      const remoto = await servidor(`/status?worker=${WORKER_ID}`).catch(() => null);
      sendResponse({ ok: true, estado: e, servidor: remoto }); return;
    }
    sendResponse({ ok: true, estado: e });
  })();
  return true;
});

setTimeout(() => { if (obterEstado().rodando) executar(); }, 1500);
