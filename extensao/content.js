console.log(
"🔥 Zap Scraper carregado"
);

// =====================================================
// CONFIGURAÇÕES GERAIS
// =====================================================
const WORKER_ID = (
  window.ZAP_WORKER_ID ||
  new URLSearchParams(location.search).get("worker") ||
  localStorage.getItem("zap_worker_id") ||
  "worker1"
).toLowerCase();
localStorage.setItem("zap_worker_id", WORKER_ID);

const KEY =
`zap_estado_${WORKER_ID}`;
const SERVER = "http://127.0.0.1:5000";

const CONFIG = {
  limite: 10000,
  maxPaginas: 50,
  delayMin: 800,
  delayMax: 2600,
  pausaTrocaMunicipioMin: 3500,
  pausaTrocaMunicipioMax: 9000,
  scrollDelayMin: 250,
  scrollDelayMax: 900,
  maxScrollsLista: 6,
  maxScrollsDetalhe: 4,
  maxReloadsPagina: 3
};

// =====================================================
// UTILS
// =====================================================
function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function delay(min = CONFIG.delayMin, max = CONFIG.delayMax) {
  const tempo = Math.floor(Math.random() * (max - min + 1)) + min;
  return sleep(tempo);
}

function delayScroll() {
  return delay(CONFIG.scrollDelayMin, CONFIG.scrollDelayMax);
}

function limparTexto(txt) {
  if (!txt) return "N/A";
  return String(txt)
    .replace(/\u00a0/g, " ")
    .replace(/[ \t]+/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim() || "N/A";
}

function textoComparavel(txt) {
  return limparTexto(txt)
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function slugTexto(txt) {
  return textoComparavel(txt)
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function textoPagina() {
  return limparTexto(document.body ? document.body.innerText : "");
}

function paginaComBloqueio() {
  const texto = textoPagina().toLowerCase();
  return (
    texto.includes("checking your browser") ||
    texto.includes("just a moment") ||
    texto.includes("verify you are human") ||
    texto.includes("cloudflare")
  );
}

function paginaIncompleta() {
  const html = document.documentElement ? document.documentElement.innerHTML : "";
  const texto = textoPagina();
  return !document.body || html.length < 500 || texto.length < 80;
}

function emitirAvisoSonoro() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.value = 880;
    gain.gain.value = 0.2;
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    setTimeout(() => {
      osc.stop();
      ctx.close();
    }, 900);
  } catch (e) {
    console.warn("Nao consegui emitir aviso sonoro:", e);
  }
}

function normalizarUrl(url) {
  try {
    const u = new URL(url, location.origin);
    u.hash = "";
    // remove rastreadores que podem gerar duplicidade do mesmo imóvel
    ["source", "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"].forEach((p) => {
      u.searchParams.delete(p);
    });
    return u.href;
  } catch (e) {
    return url;
  }
}

function hojeHora() {
  const agora = new Date();
  const data = agora.toISOString().slice(0, 10);
  const hora = agora.toTimeString().slice(0, 8);
  return { data_coleta: data, hora_coleta: hora };
}

function primeiroMatch(texto, regex, padrao = "N/A") {
  const m = texto.match(regex);
  return m ? limparTexto(m[1] || m[0]) : padrao;
}

function contemPreco(texto) {
  return /R\$\s*[\d\.]+(?:,\d{2})?/.test(texto || "");
}

function extrairPrecoTexto(texto) {
  return primeiroMatch(texto, /R\$\s*[\d\.]+(?:,\d{2})?/, "N/A");
}

function extrairMetragemTexto(texto) {
  return primeiroMatch(texto, /(\d+(?:[\.,]\d+)?)\s*m²/i, "N/A");
}

function extrairQuartosTexto(texto) {
  let m = texto.match(/(\d+)\s*(?:quarto|quartos|dormitório|dormitórios)/i);
  if (m) return m[1];

  // Em alguns cards o número vem sozinho em uma linha ao lado do ícone de quarto.
  m = texto.match(/\n\s*(\d+)\s*\n\s*(?:banheiro|banheiros|vaga|vagas)/i);
  return m ? m[1] : "N/A";
}

function extrairLocalizacaoTexto(texto) {
  const linhas = limparTexto(texto).split("\n").map(limparTexto).filter(Boolean);

  const estado = (getEstado().estadoAtual || "SP").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const municipio = (getEstado().municipioAtual || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const regexCidade = municipio ? new RegExp(`${municipio}(\\s*-\\s*${estado})?`, "i") : null;
  const linhaComCidade = regexCidade ? linhas.find((l) => regexCidade.test(l)) : null;
  if (linhaComCidade) return linhaComCidade;

  const linhaComRua = linhas.find((l) =>
    /^(Rua|Avenida|Av\.|Travessa|Alameda|Praça|R\.)\b/i.test(l)
  );
  if (linhaComRua) return linhaComRua;

  return "N/A";
}

function ehPaginaDetalhe() {
  return location.pathname.includes("/imovel/");
}

function parsePaginaDaUrl(url) {
  try {
    const u = new URL(url);
    return Number(u.searchParams.get("pagina") || u.searchParams.get("page") || 1);
  } catch (e) {
    return 1;
  }
}

function criarEstadoPadrao() {
  return {
    rodando: false,
    limite: CONFIG.limite,
    maxPaginas: CONFIG.maxPaginas,
    paginaAtual: 1,
    listaUrlAtual: null,
    proximaListaUrl: null,
    filaLinks: [],
    filaDadosLista: {},
    filaIndex: 0,
    urlsVisitadas: [],
    detalhesSalvos: 0,
    paginasVisitadas: [],
    municipioAtual: null,
    estadoAtual: null,
    municipioUrl: null,
    municipiosConcluidos: 0,
    municipiosRestantes: null,
    cidadeIniciadaEm: null,
    totalIniciadoEm: null,
    paginasProcessadas: 0,
    reloadsPagina: 0,
    ultimoStatus: "aguardando início",
    ultimoUrl: null,
    erros: 0
  };
}

function getEstado() {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? JSON.parse(raw) : criarEstadoPadrao();
  } catch (e) {
    return criarEstadoPadrao();
  }
}

function setEstado(estado) {
  localStorage.setItem(KEY, JSON.stringify(estado));
}

function resetEstado() {
  const estado = criarEstadoPadrao();
  setEstado(estado);
  return estado;
}

function coletaAtiva() {
  const estado = getEstado();
  return !!(estado && estado.rodando);
}

function jaVisitou(estado, url) {
  return (estado.urlsVisitadas || []).includes(normalizarUrl(url));
}

function marcarVisitado(estado, url) {
  const normalizada = normalizarUrl(url);
  if (!estado.urlsVisitadas) estado.urlsVisitadas = [];
  if (!estado.urlsVisitadas.includes(normalizada)) estado.urlsVisitadas.push(normalizada);

  // Evita estourar o localStorage em coletas muito grandes.
  if (estado.urlsVisitadas.length > 12000) {
    estado.urlsVisitadas = estado.urlsVisitadas.slice(-12000);
  }
}

// =====================================================
// COMUNICAÇÃO COM O SERVIDOR LOCAL
// =====================================================
// Importante: no Chrome atual, uma página HTTPS como o Viva Real pode ser
// bloqueada ao tentar acessar diretamente http://127.0.0.1:5000.
// Por isso o content script envia a requisição para o background.js da extensão,
// e o background faz o fetch para o servidor Flask local.
function chamarServidorPeloBackground(endpoint, method = "GET", payload = null) {
  return new Promise((resolve, reject) => {
    const separador = endpoint.includes("?") ? "&" : "?";
    const endpointWorker = `${endpoint}${separador}worker=${encodeURIComponent(WORKER_ID)}`;
    chrome.runtime.sendMessage(
      {
        tipo: "fetch_servidor",
        endpoint: endpointWorker,
        method,
        payload: payload ? { worker: WORKER_ID, ...payload } : { worker: WORKER_ID }
      },
      (resposta) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
          return;
        }

        if (!resposta) {
          reject(new Error("Sem resposta do background.js"));
          return;
        }

        resolve(resposta);
      }
    );
  });
}

async function enviar(endpoint, payload) {
  const resposta = await chamarServidorPeloBackground(endpoint, "POST", payload);

  if (!resposta.ok) {
    throw new Error(resposta.erro || `Servidor respondeu ${resposta.status}`);
  }

  return resposta.data;
}

async function obterStatusServidor() {
  try {
    const resposta = await chamarServidorPeloBackground("/status", "GET");
    return resposta.ok ? resposta.data : null;
  } catch (e) {
    return null;
  }
}

async function registrarLog(nivel, mensagem, extra = {}) {
  try {
    await enviar(`/worker/${WORKER_ID}/log`, { nivel, mensagem, ...extra });
  } catch (e) {
    console.warn("Falha ao registrar log:", e);
  }
}

async function salvarCheckpointServidor(estado, extra = {}) {
  try {
    await enviar(`/worker/${WORKER_ID}/checkpoint`, {
      rodando: estado.rodando,
      pagina_atual: estado.paginaAtual,
      municipio_atual: estado.municipioAtual,
      estado_atual: estado.estadoAtual,
      ultima_url: location.href,
      detalhes_salvos: estado.detalhesSalvos || 0,
      reloads: estado.reloadsPagina || 0,
      erros: estado.erros || 0,
      ultimo_status: estado.ultimoStatus,
      ...extra
    });
  } catch (e) {
    console.warn("Falha ao salvar checkpoint no servidor:", e);
  }
}

async function marcarPaginaProcessada(estado, status) {
  estado.paginasProcessadas = (estado.paginasProcessadas || 0) + 1;
  setEstado(estado);
  try {
    await enviar(`/worker/${WORKER_ID}/pagina-processada`, {
      pagina: estado.paginaAtual,
      url: location.href,
      status
    });
  } catch (e) {
    console.warn("Falha ao registrar pagina processada:", e);
  }
}

async function obterProximoMunicipio(estado) {
  const resposta = await chamarServidorPeloBackground(`/worker/${WORKER_ID}/proximo-municipio`, "POST", {
    pagina_atual: estado.paginaAtual || 1
  });
  if (!resposta.ok || !resposta.data || !resposta.data.ok) {
    throw new Error(resposta.erro || "Nao consegui obter o proximo municipio.");
  }
  return resposta.data;
}

async function filtrarUrlsDetalheNoServidor(estado, urls) {
  const resposta = await chamarServidorPeloBackground(
    `/worker/${WORKER_ID}/filtrar-urls-detalhe`,
    "POST",
    {
      municipio: estado.municipioAtual,
      estado: estado.estadoAtual,
      urls
    }
  );

  if (!resposta.ok || !resposta.data || !resposta.data.ok) {
    throw new Error(resposta.erro || "Nao consegui filtrar URLs ja coletadas.");
  }

  return resposta.data;
}

// =====================================================
// SCROLL E CLIQUES DE EXPANSÃO
// =====================================================
async function scrollSuave(maxScrolls) {
  let alturaAnterior = 0;

  for (let i = 0; i < maxScrolls; i++) {
    const direcao = i % 5 === 4 ? -0.18 : 0.65 + Math.random() * 0.35;
    window.scrollBy(0, Math.floor(window.innerHeight * direcao));
    await delayScroll();

    const alturaAtual = document.body.scrollHeight;
    if (alturaAtual === alturaAnterior && i > 2) break;
    alturaAnterior = alturaAtual;
  }
}

async function expandirDescricao() {
  const botoes = [...document.querySelectorAll("button, a, span, div")];
  const alvo = botoes.find((el) => {
    const t = limparTexto(el.innerText || "").toLowerCase();
    return t === "descrição completa" || t === "descricao completa" || t.includes("ver descrição completa") || t.includes("ver descricao completa");
  });

  if (alvo) {
    try {
      alvo.click();
      await sleep(1000);
    } catch (e) {
      console.log("Não consegui expandir descrição:", e);
    }
  }
}

// =====================================================
// EXTRAÇÃO DA LISTAGEM
// CSV esperado: url;preco;metragem;quartos;localizacao;descricao
// =====================================================
function obterCardRaiz(link) {
  let atual = link;

  for (let i = 0; i < 8 && atual; i++) {
    const texto = limparTexto(atual.innerText || "");

    if (
      texto.length > 80 &&
      texto.length < 2500 &&
      contemPreco(texto) &&
      /m²/i.test(texto)
    ) {
      return atual;
    }

    atual = atual.parentElement;
  }

  return link;
}

function extrairDescricaoCard(texto) {
  const linhas = limparTexto(texto).split("\n").map(limparTexto).filter(Boolean);

  const ignorar = [
    /^R\$/i,
    /^Cond\./i,
    /^IPTU/i,
    /^Mensagem$/i,
    /^Contatar$/i,
    /^Favoritar$/i,
    /^\+?\d+ fotos?$/i,
    /^Preço abaixo/i,
    /^PUBLICIDADE$/i
  ];

  const linha = linhas.find((l) => {
    if (ignorar.some((r) => r.test(l))) return false;
    if (/^\d+\s*m²$/i.test(l)) return false;
    if (/^\d+$/.test(l)) return false;
    return l.length >= 25;
  });

  return linha || linhas[0] || "N/A";
}
function extrairTipoImovelTexto(texto) {

    const tipos = [
        "Casa de condomínio",
        "Casa de Condominio",
        "Casa de Vila",
        "Apartamento",
        "Sobrado",
        "Terreno",
        "Kitnet",
        "Cobertura",
        "Flat",
        "Loft",
        "Casa"
    ];

    for (const tipo of tipos) {

        const regex =
            new RegExp(tipo, "i");

        if (regex.test(texto)) {
            return tipo;
        }
    }

    return "N/A";
}
function extrairItensDaLista() {
  console.log(
    "LINKS ENCONTRADOS:",
    document.querySelectorAll(
        "a[href*='/imovel/']"
    ).length
);
  const links = [...document.querySelectorAll("a[href*='/imovel/']")];
  const mapa = new Map();
  const coleta = hojeHora();

  for (const link of links) {
    const url = normalizarUrl(link.href);
    if (!url.includes("/imovel/")) continue;

    const card = obterCardRaiz(link);
    const texto = limparTexto(card.innerText || link.innerText || "");

    if (!texto || texto.length < 20) continue;

    const item = {
      url,
      tipo_imovel:
          extrairTipoImovelTexto(texto),
      preco: extrairPrecoTexto(texto),
      metragem: extrairMetragemTexto(texto),
      quartos: extrairQuartosTexto(texto),
      localizacao: extrairLocalizacaoTexto(texto),
      descricao: extrairDescricaoCard(texto),
      data_coleta: coleta.data_coleta,
      hora_coleta: coleta.hora_coleta
    };

    if (!mapa.has(url)) mapa.set(url, item);
  }

  const resultado =
    [...mapa.values()];

  console.log(
      "ITENS DA LISTA:",
      resultado.length
  );

  return resultado;
}

function encontrarProximaPagina() {
  const paginaAtual = parsePaginaDaUrl(location.href);
  if (paginaAtual >= CONFIG.maxPaginas) return null;
  const candidatos = [...document.querySelectorAll("a[href], button")];

  for (const el of candidatos) {
    const texto = limparTexto([
      el.innerText,
      el.getAttribute("aria-label"),
      el.getAttribute("title")
    ].filter(Boolean).join(" ")).toLowerCase();

    if (/próxima|proxima|seguinte|next|avançar|avancar/.test(texto)) {
      if (el.href && parsePaginaDaUrl(el.href) <= CONFIG.maxPaginas) return el.href;
      const linkInterno = el.querySelector && el.querySelector("a[href]");
      if (linkInterno && parsePaginaDaUrl(linkInterno.href) <= CONFIG.maxPaginas) return linkInterno.href;
    }
  }

  // Fallback: incrementa ?pagina=N, que é comum em páginas paginadas.
  try {
    const u = new URL(location.href);
    const atual = Number(u.searchParams.get("pagina") || u.searchParams.get("page") || 1);
    if (atual >= CONFIG.maxPaginas) return null;
    u.searchParams.set("pagina", String(atual + 1));
    return u.href;
  } catch (e) {
    return null;
  }
}

function extrairTotalAnunciosSite() {

    const texto = textoPagina();

    let m = texto.match(
        /([\d\.]+)\s+.*?para venda/i
    );

    if (m) {
        return m[1];
    }

    return "N/A";
}
// =====================================================
// EXTRAÇÃO DA PÁGINA DO ANÚNCIO
// CSV esperado: url;preco;metragem;quartos;anunciante;localizacao;descricao;data_anuncio;data_coleta;hora_coleta
// =====================================================
function obterTituloPrincipal() {
  const h1 = document.querySelector("h1");
  return h1 ? limparTexto(h1.innerText) : "";
}

function extrairPrecoDetalhe() {

    let container =
        document.querySelector("#price-section");

    if (!container)
        return "N/A";

    let valores =
        container.querySelectorAll(
            ".value-item__value"
        );

    if (!valores.length)
        return "N/A";

    return valores[0].innerText.trim();
}

function extrairMetragemDetalhe() {
  const titulo = obterTituloPrincipal();
  const valorTitulo = extrairMetragemTexto(titulo);
  if (valorTitulo !== "N/A") return valorTitulo;

  const texto = textoPagina();
  const blocoCaracteristicas = texto.match(/Características do imóvel[\s\S]{0,500}/i);
  if (blocoCaracteristicas) {
    const metragem = extrairMetragemTexto(blocoCaracteristicas[0]);
    if (metragem !== "N/A") return metragem;
  }

  return extrairMetragemTexto(texto);
}

function extrairQuartosDetalhe() {
  const titulo = obterTituloPrincipal();
  const valorTitulo = extrairQuartosTexto(titulo);
  if (valorTitulo !== "N/A") return valorTitulo;

  const texto = textoPagina();
  const blocoCaracteristicas = texto.match(/Características do imóvel[\s\S]{0,500}/i);
  if (blocoCaracteristicas) {
    const quartos = extrairQuartosTexto(blocoCaracteristicas[0]);
    if (quartos !== "N/A") return quartos;
  }

  return extrairQuartosTexto(texto);
}

function extrairLocalizacaoDetalhe() {

    return document.querySelector(
        '[data-testid="location-address"]'
    )?.innerText?.trim()
    || "N/A";

}

function extrairDescricaoDetalhe() {

    return document.querySelector(
        '[data-testid="description-content"]'
    )?.innerText?.trim()
    || "N/A";

}

function extrairAnuncianteDetalhe() {

    return document.querySelector(
        '[data-testid="official-store-redirect-link"] span'
    )?.innerText?.trim()
    || "N/A";

}

function extrairDataAnuncioDetalhe() {

    return document.querySelector(
        '[data-testid="listing-created-date"]'
    )?.innerText?.trim()
    || "N/A";

}

function extrairTipoImovelDetalhe() {

    const h1 =
        document.querySelector("h1")
        ?.innerText || "";

    return extrairTipoImovelTexto(h1);
}

function extrairDadosDetalhe() {
  const coleta = hojeHora();

  return {
    url: normalizarUrl(location.href),

    tipo_imovel: extrairTipoImovelDetalhe(),

    preco: extrairPrecoDetalhe(),
    metragem: extrairMetragemDetalhe(),
    quartos: extrairQuartosDetalhe(),

    anunciante: extrairAnuncianteDetalhe(),
    localizacao: extrairLocalizacaoDetalhe(),
    descricao: extrairDescricaoDetalhe(),

    data_anuncio: extrairDataAnuncioDetalhe(),

    data_coleta: coleta.data_coleta,
    hora_coleta: coleta.hora_coleta
  };
}

// =====================================================
// FLUXO PRINCIPAL
// =====================================================
async function tratarBloqueioSeExistir(estado) {
  if (!paginaComBloqueio()) return false;

  estado.rodando = false;
  estado.ultimoStatus = "BLOQUEIO: Cloudflare/verificacao humana detectada";
  setEstado(estado);
  emitirAvisoSonoro();
  alert("Coleta interrompida: o Zap/Cloudflare pediu verificacao humana neste worker.");
  await enviar(`/worker/${WORKER_ID}/bloqueio`, {
    mensagem: estado.ultimoStatus,
    url: location.href,
    municipio: estado.municipioAtual,
    pagina: estado.paginaAtual
  });
  return true;
}

async function recuperarPaginaSeNecessario(estado) {
  if (!paginaIncompleta()) {
    estado.reloadsPagina = 0;
    setEstado(estado);
    return false;
  }

  estado.reloadsPagina = (estado.reloadsPagina || 0) + 1;
  estado.erros = (estado.erros || 0) + 1;
  estado.ultimoStatus = `pagina incompleta; reload ${estado.reloadsPagina}/${CONFIG.maxReloadsPagina}`;
  setEstado(estado);
  await registrarLog("warning", estado.ultimoStatus, { url: location.href });

  if (estado.reloadsPagina <= CONFIG.maxReloadsPagina) {
    await delay(2500, 7000);
    location.reload();
    return true;
  }

  estado.ultimoStatus = "pagina incompleta apos 3 tentativas; aguardando acao manual";
  estado.rodando = false;
  setEstado(estado);
  await salvarCheckpointServidor(estado);
  return true;
}

async function garantirMunicipioAtual(estado) {
  const resposta = await obterProximoMunicipio(estado);
  if (resposta.finalizado) {
    estado.rodando = false;
    estado.ultimoStatus = "todos os municipios do worker foram concluidos";
    setEstado(estado);
    return estado;
  }

  const municipio = resposta.municipio;
  estado.municipioAtual = municipio.municipio;
  estado.estadoAtual = municipio.estado;
  estado.municipioUrl = municipio.url;
  estado.paginaAtual = (resposta.checkpoint && resposta.checkpoint.pagina_atual) || 1;
  estado.municipiosConcluidos = resposta.stats ? resposta.stats.municipios_concluidos : estado.municipiosConcluidos;
  estado.municipiosRestantes = resposta.stats ? resposta.stats.municipios_restantes : estado.municipiosRestantes;
  estado.cidadeIniciadaEm = estado.cidadeIniciadaEm || Date.now();
  estado.totalIniciadoEm = estado.totalIniciadoEm || Date.now();
  estado.ultimoStatus = `iniciando municipio: ${estado.municipioAtual}`;
  setEstado(estado);

  const detalheSolto = ehPaginaDetalhe() && (!(estado.filaLinks || []).length || !estado.listaUrlAtual);
  if ((!ehPaginaDetalhe() || detalheSolto) && !mesmaUrlSemHash(location.href, estado.municipioUrl)) {
    await delay(CONFIG.pausaTrocaMunicipioMin, CONFIG.pausaTrocaMunicipioMax);
    if (!coletaAtiva()) return getEstado();
    location.assign(estado.municipioUrl);
  }

  return estado;
}

async function concluirMunicipio(estado, motivo) {
  const municipio = estado.municipioAtual;
  await enviar(`/worker/${WORKER_ID}/municipio-concluido`, {
    municipio,
    estado: estado.estadoAtual,
    motivo
  });

  const novo = criarEstadoPadrao();
  novo.rodando = true;
  novo.totalIniciadoEm = estado.totalIniciadoEm || Date.now();
  novo.municipiosConcluidos = (estado.municipiosConcluidos || 0) + 1;
  novo.ultimoStatus = `municipio concluido: ${municipio}`;
  setEstado(novo);
  await delay(CONFIG.pausaTrocaMunicipioMin, CONFIG.pausaTrocaMunicipioMax);
  if (!coletaAtiva()) return;

  const resposta = await obterProximoMunicipio(novo);
  if (resposta.finalizado) {
    novo.rodando = false;
    novo.ultimoStatus = "todos os municipios do worker foram concluidos";
    setEstado(novo);
    return;
  }

  novo.municipioAtual = resposta.municipio.municipio;
  novo.estadoAtual = resposta.municipio.estado;
  novo.municipioUrl = resposta.municipio.url;
  novo.municipiosRestantes = resposta.stats ? resposta.stats.municipios_restantes : null;
  novo.cidadeIniciadaEm = Date.now();
  novo.ultimoStatus = `indo para proximo municipio: ${novo.municipioAtual}`;
  setEstado(novo);
  if (!coletaAtiva()) return;
  location.assign(novo.municipioUrl);
}

async function registrarMunicipioSemImoveis(estado) {
  estado.ultimoStatus = `municipio sem imoveis: ${estado.municipioAtual}`;
  setEstado(estado);
  await enviar(`/worker/${WORKER_ID}/municipio-sem-imoveis`, {
    municipio: estado.municipioAtual,
    estado: estado.estadoAtual
  });

  const novo = criarEstadoPadrao();
  novo.rodando = true;
  novo.totalIniciadoEm = estado.totalIniciadoEm || Date.now();
  novo.municipiosConcluidos = (estado.municipiosConcluidos || 0) + 1;
  novo.ultimoStatus = "indo para proximo municipio apos SEM_IMOVEIS";
  setEstado(novo);
  await delay(CONFIG.pausaTrocaMunicipioMin, CONFIG.pausaTrocaMunicipioMax);
  if (!coletaAtiva()) return;

  const resposta = await obterProximoMunicipio(novo);
  if (resposta.finalizado) {
    novo.rodando = false;
    novo.ultimoStatus = "todos os municipios do worker foram concluidos";
    setEstado(novo);
    return;
  }

  novo.municipioAtual = resposta.municipio.municipio;
  novo.estadoAtual = resposta.municipio.estado;
  novo.municipioUrl = resposta.municipio.url;
  novo.municipiosRestantes = resposta.stats ? resposta.stats.municipios_restantes : null;
  novo.cidadeIniciadaEm = Date.now();
  setEstado(novo);
  if (!coletaAtiva()) return;
  location.assign(novo.municipioUrl);
}

function paginaPareceSerDoMunicipio(estado) {
  const municipio = estado.municipioAtual || "";
  if (!municipio) return true;

  const municipioTexto = textoComparavel(municipio);
  const municipioSlug = slugTexto(municipio);
  const urlAtual = textoComparavel(decodeURIComponent(location.href));
  const pathAtual = slugTexto(location.pathname || "");
  const texto = textoComparavel(textoPagina());

  return (
    urlAtual.includes(municipioTexto) ||
    pathAtual.includes(municipioSlug) ||
    texto.includes(municipioTexto)
  );
}

function paginaTemMensagemSemImoveis() {
  const texto = textoComparavel(textoPagina());
  return (
    texto.includes("nenhum imovel encontrado") ||
    texto.includes("nao encontramos imoveis") ||
    texto.includes("nao encontramos anuncios") ||
    texto.includes("sem anuncios") ||
    texto.includes("0 imoveis")
  );
}

async function registrarUrlInvalidaEAvancar(estado) {
  estado.ultimoStatus = `URL_INVALIDA: enviando ${estado.municipioAtual} para repescagem`;
  setEstado(estado);
  await enviar(`/worker/${WORKER_ID}/municipio-url-invalida`, {
    municipio: estado.municipioAtual,
    estado: estado.estadoAtual,
    url: location.href
  });
  await registrarLog("warning", estado.ultimoStatus, {
    municipio: estado.municipioAtual,
    estado: estado.estadoAtual,
    url: location.href,
  });

  const novo = criarEstadoPadrao();
  novo.rodando = true;
  novo.totalIniciadoEm = estado.totalIniciadoEm || Date.now();
  novo.municipiosConcluidos = (estado.municipiosConcluidos || 0) + 1;
  novo.ultimoStatus = "indo para proximo municipio apos URL_INVALIDA";
  setEstado(novo);
  await delay(CONFIG.pausaTrocaMunicipioMin, CONFIG.pausaTrocaMunicipioMax);
  if (!coletaAtiva()) return;

  const resposta = await obterProximoMunicipio(novo);
  if (resposta.finalizado) {
    novo.rodando = false;
    novo.ultimoStatus = "todos os municipios do worker foram concluidos";
    setEstado(novo);
    return;
  }

  novo.municipioAtual = resposta.municipio.municipio;
  novo.estadoAtual = resposta.municipio.estado;
  novo.municipioUrl = resposta.municipio.url;
  novo.municipiosRestantes = resposta.stats ? resposta.stats.municipios_restantes : null;
  novo.cidadeIniciadaEm = Date.now();
  setEstado(novo);
  if (!coletaAtiva()) return;
  location.assign(novo.municipioUrl);
}
function mesmaUrlSemHash(a, b) {
  try {
    const ua = new URL(a, location.origin);
    const ub = new URL(b, location.origin);
    ua.hash = "";
    ub.hash = "";
    return ua.href === ub.href;
  } catch (e) {
    return a === b;
  }
}

function temFilaPendenteDaListaAtual(estado) {
  const fila = estado.filaLinks || [];
  const index = estado.filaIndex || 0;
  return (
    fila.length > 0 &&
    index < fila.length &&
    estado.listaUrlAtual &&
    mesmaUrlSemHash(estado.listaUrlAtual, location.href)
  );
}

async function irParaProximoDetalheOuPagina(estado) {
  if ((estado.detalhesSalvos || 0) >= estado.limite) {
    estado.rodando = false;
    estado.ultimoStatus = `limite de ${estado.limite} detalhes atingido`;
    setEstado(estado);
    return;
  }

  const fila = estado.filaLinks || [];
  const index = estado.filaIndex || 0;

  if (index < fila.length) {
    const proximo = fila[index];
    estado.ultimoStatus = `indo para anúncio ${index + 1}/${fila.length}`;
    estado.ultimoUrl = proximo;
    setEstado(estado);
    await delay();
    if (!coletaAtiva()) return;
    location.assign(proximo);
    return;
  }

  if (estado.proximaListaUrl && estado.paginaAtual < estado.maxPaginas) {
    estado.paginaAtual += 1;
    estado.filaLinks = [];
    estado.filaDadosLista = {};
    estado.filaIndex = 0;
    estado.ultimoStatus = `indo para página ${estado.paginaAtual}`;
    setEstado(estado);
    await salvarCheckpointServidor(estado);
    await delay();
    if (!coletaAtiva()) return;
    location.assign(estado.proximaListaUrl);
    return;
  }

  estado.ultimoStatus = estado.paginaAtual >= estado.maxPaginas
    ? "municipio finalizado: limite de 50 paginas"
    : "municipio finalizado: nao encontrei proxima pagina";
  setEstado(estado);
  await concluirMunicipio(estado, estado.ultimoStatus);
}

async function voltarParaListaDepoisDoDetalhe(estado) {
  // Fluxo no estilo do Zap: detalhe -> volta para a listagem -> próximo anúncio.
  if (estado.listaUrlAtual) {
    estado.ultimoStatus = `voltando para a lista para continuar no índice ${(estado.filaIndex || 0) + 1}`;
    setEstado(estado);
    await delay(700, 1500);
    if (!coletaAtiva()) return;
    location.assign(estado.listaUrlAtual);
    return;
  }

  // Fallback: se a coleta começou em um anúncio aberto manualmente, tenta voltar pelo histórico.
  estado.rodando = false;
  estado.ultimoStatus = "detalhe salvo, mas não há lista salva no estado. Comece a coleta pela página de listagem.";
  setEstado(estado);
  try {
    history.back();
  } catch (e) {
    console.log("Não consegui voltar pelo histórico:", e);
  }
}

async function processarPaginaLista(estado) {
  // Se voltamos de um anúncio para a mesma lista, não recomeça a página.
  // Apenas continua do próximo link da fila já coletada.
  if (temFilaPendenteDaListaAtual(estado)) {
    estado.ultimoStatus = `de volta à lista; continuando anúncio ${(estado.filaIndex || 0) + 1}/${(estado.filaLinks || []).length}`;
    setEstado(estado);
    await delay(500, 1200);
    await irParaProximoDetalheOuPagina(estado);
    return;
  }

  // Se a fila acabou e já temos uma próxima página guardada, avança a listagem.
  if (
    estado.listaUrlAtual &&
    mesmaUrlSemHash(estado.listaUrlAtual, location.href) &&
    (estado.filaLinks || []).length > 0 &&
    (estado.filaIndex || 0) >= (estado.filaLinks || []).length
  ) {
    await irParaProximoDetalheOuPagina(estado);
    return;
  }

  estado.listaUrlAtual = location.href;
  estado.paginaAtual = parsePaginaDaUrl(location.href);
  estado.ultimoStatus = "rolando página de listagem";
  setEstado(estado);

  await scrollSuave(CONFIG.maxScrollsLista);
  await delay(1000, 2500);

  const totalSite = extrairTotalAnunciosSite();
  for(let i=0;i<10;i++){

    const qtd =
        document.querySelectorAll(
            "a[href*='/imovel/']"
        ).length;

    console.log(
        "Tentativa",
        i,
        "cards:",
        qtd
    );

    if(qtd >= 10){
        break;
    }

    await sleep(1000);
}
   
   
 const linksPagina =
[
    ...document.querySelectorAll(
        "a[href*='/imovel/']"
    )
]
.map(a => normalizarUrl(a.href));

if (linksPagina.length === 0 && !paginaPareceSerDoMunicipio(estado)) {
    await registrarUrlInvalidaEAvancar(estado);
    return;
}

const linksUnicosPagina = [...new Set(linksPagina)];
const candidatosLocais = linksUnicosPagina.filter(url => !jaVisitou(estado, url));
let filtroServidor = { novas: candidatosLocais, repetidas: [] };

try {
  filtroServidor = await filtrarUrlsDetalheNoServidor(estado, candidatosLocais);
} catch (e) {
  estado.erros = (estado.erros || 0) + 1;
  estado.ultimoStatus = "erro ao consultar URLs ja coletadas no servidor";
  setEstado(estado);
  console.error(e);
  return;
}

const novosLinks = filtroServidor.novas || [];

console.log(
    "NOVOS LINKS:",
    novosLinks.length,
    "REPETIDOS NO CSV:",
    (filtroServidor.repetidas || []).length
);

const proximaEncontrada = encontrarProximaPagina();
estado.proximaListaUrl = proximaEncontrada ? normalizarUrl(proximaEncontrada) : null;

if (!novosLinks.length) {

    console.log(
        "Nenhum link novo."
    );

    if ((estado.paginaAtual || 1) === 1 && linksPagina.length === 0 && paginaPareceSerDoMunicipio(estado)) {
        if (!paginaTemMensagemSemImoveis()) {
            await registrarLog("warning", "pagina sem links e sem mensagem clara de sem imoveis", {
                municipio: estado.municipioAtual,
                url: location.href
            });
        }
        await registrarMunicipioSemImoveis(estado);
        return;
    }

    await irParaProximoDetalheOuPagina(
        estado
    );

    return;
}

  const itens = extrairItensDaLista().filter((item) => linksUnicosPagina.includes(item.url));

  try {
    const resposta = await enviar("/dados-lista", {
      itens,
      pagina: estado.paginaAtual,
      total_site: totalSite,
      municipio: estado.municipioAtual,
      estado: estado.estadoAtual
    });
    console.log("Lista salva:", resposta);
  } catch (e) {
    estado.erros = (estado.erros || 0) + 1;
    estado.ultimoStatus = "erro ao enviar listagem para o servidor; verifique se server.py esta rodando";
    setEstado(estado);
    console.error(e);
    return;
  }


  const mapaDados = {};

  estado.filaLinks = novosLinks;
  estado.filaDadosLista = mapaDados;
  estado.filaIndex = 0;

  if (novosLinks.length === 0) {
    estado.paginasSemLinksNovos = (estado.paginasSemLinksNovos || 0) + 1;
  } else {
    estado.paginasSemLinksNovos = 0;
  }

  if (estado.paginasSemLinksNovos >= 3) {
    estado.rodando = false;
    estado.ultimoStatus = "parei após 3 páginas seguidas sem links novos";
    setEstado(estado);
    return;
  }

  estado.ultimoStatus = `página ${estado.paginaAtual}: ${novosLinks.length} anúncios novos. Total informado pelo site: ${totalSite}`;
  setEstado(estado);
  await marcarPaginaProcessada(estado, estado.ultimoStatus);

  await irParaProximoDetalheOuPagina(estado);
}

async function processarPaginaDetalhe(estado) {
  estado.ultimoStatus = "rolando página de detalhe";
  setEstado(estado);

  await sleep(1500);
  await expandirDescricao();
  await scrollSuave(CONFIG.maxScrollsDetalhe);
  await delay(1000, 2500);

  const dados = extrairDadosDetalhe();
  dados.worker = WORKER_ID;
  dados.municipio = estado.municipioAtual;
  dados.estado = estado.estadoAtual;
  console.log("📦 Detalhe extraído:", dados);

  try {
    const resposta = await enviar("/dados-detalhe", dados);
    console.log("Detalhe salvo:", resposta);

    estado.detalhesSalvos = resposta.total_detalhes || ((estado.detalhesSalvos || 0) + 1);
    marcarVisitado(estado, dados.url);
    estado.filaIndex = (estado.filaIndex || 0) + 1;
    estado.ultimoStatus = `detalhe salvo: ${estado.detalhesSalvos}/${estado.limite}`;
    setEstado(estado);
    await salvarCheckpointServidor(estado);
  } catch (e) {
    estado.erros = (estado.erros || 0) + 1;
    estado.ultimoStatus = "erro ao enviar detalhe para o servidor; verifique se server.py está rodando";
    setEstado(estado);
    console.error(e);
    return;
  }

  await voltarParaListaDepoisDoDetalhe(estado);
}

async function executar() {
  if (window.__vivaRealExecutando) return;
  window.__vivaRealExecutando = true;

  try {
    let estado = getEstado();
    if (!estado.rodando) return;

    if (await tratarBloqueioSeExistir(estado)) return;
    if (await recuperarPaginaSeNecessario(estado)) return;

    estado = await garantirMunicipioAtual(estado);
    if (!estado.rodando) return;

    if ((estado.detalhesSalvos || 0) >= estado.limite) {
      estado.rodando = false;
      estado.ultimoStatus = `limite de ${estado.limite} atingido`;
      setEstado(estado);
      return;
    }

    if (ehPaginaDetalhe()) {
      await processarPaginaDetalhe(estado);
    } else {
      await processarPaginaLista(estado);
    }
  } finally {
    window.__vivaRealExecutando = false;
  }
}

setInterval(() => {
  const estado = getEstado();
  if (estado && estado.rodando) executar();
}, 5000);

// =====================================================
// START / STOP / RESET / STATUS
// =====================================================
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  let estado = getEstado();

  if (msg.action === "start") {
    estado = criarEstadoPadrao();
    estado.rodando = true;
    estado.limite = CONFIG.limite;
    estado.maxPaginas = CONFIG.maxPaginas;
    estado.totalIniciadoEm = Date.now();
    estado.ultimoStatus = "coleta iniciada";

    setEstado(estado);
    sendResponse({ ok: true, estado });
    salvarCheckpointServidor(estado);
    executar();
    return true;
  }

  if (msg.action === "stop") {
    estado.rodando = false;
    estado.ultimoStatus = "coleta pausada pelo usuario";
    setEstado(estado);
    salvarCheckpointServidor(estado, { rodando: false, ultimo_status: estado.ultimoStatus });
    sendResponse({ ok: true, estado });
    return true;
  }

  if (msg.action === "reset") {
    estado = resetEstado();
    sendResponse({ ok: true, estado });
    return true;
  }

  if (msg.action === "status") {
    obterStatusServidor().then((status) => {
      if (status && typeof status.total_detalhes === "number") {
        estado.detalhesSalvos = status.total_detalhes;
        setEstado(estado);
      }
      sendResponse({ ok: true, estado, servidor: status });
    });
    return true;
  }
});


