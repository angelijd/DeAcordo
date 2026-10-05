/**
 * EXTRAÇÕES DE SIMULADORES (3 cenários) + PAINEL DE PROGRESSO
 *
 *  1) Crescimento  : aba Simulador, col. G, linhas 38-57, valor > 0
 *  2) Renovação        : pré-filtro + preço na aba "Material opcional" (col. T renovação, col. O ampliação)
 *  3) Simulador antigo : pré-filtro + preço na aba Simulador, col. W (linhas 23-40)
 *
 *  Em 2 e 3, cada simulador passa por duas etapas na mesma leitura:
 *   a) PRÉ-FILTRO, aba "Resumo da negociação": toda célula da coluna B que contém
 *      "Bonificação de material" com valor > 0 na coluna D => tem material bonificado
 *      (uma linha na aba "Bonificados_..."). Nenhuma célula encontrada => log.
 *   b) PREÇO: só nos simuladores aprovados no pré-filtro, lê a aba de preços e grava uma
 *      linha por material (formato da Beatriz) na aba "Resultado_...".
 *      Pré-filtro positivo e nenhum preço encontrado => log "DIVERGÊNCIA".
 *  GERAL.SO_PREFILTRO = true roda só a etapa a (para medir volume).
 *  Renovação e Simulador antigo rodam sobre grupos diferentes de linhas da planilha base
 *  (filtre/oculte as linhas do modelo que quer analisar; só as visíveis entram).
 *
 * Regras comuns: pedidos de QUALQUER data cujo CNPJ (col. E da planilha base) esteja na aba
 * "CNPJs" (col. A, a partir da linha 2); só linhas visíveis; link na col. G (SIMULADOR);
 * sem acesso => pula e registra no log; uma linha por simulador.
 * Link repetido: vale o pedido mais recente (col. F, FECHAMENTO).
 *
 * Tudo que é coletado é gravado nas abas de resultado a cada poucos registros e o
 * ponto onde parou é salvo junto: se algo falhar, a próxima rodada continua dali.
 * Menu "Simulador" > "Abrir painel de progresso" mostra tudo ao vivo.
 */

// ===================== CONFIGURAÇÃO (mude os nomes das abas aqui) =====================
const GERAL = {
  ABA_APROVACOES: 'Aprovacoes',
  SO_PREFILTRO: false,             // true = só a etapa "Bonificação de material" (não lê preços)
  DATA_INICIO: null,               // null = qualquer data (ou new Date(2026, 8, 1) para filtrar)
  FILTRAR_CNPJ: true,              // só pedidos cujo CNPJ está na aba abaixo
  ABA_CNPJS: 'CNPJs',              // lista de CNPJs: coluna A, a partir da linha 2
  // Colunas da planilha base (aba Aprovacoes): A FRENTE, B MARCA(S), C SOLICITANTE, D REDE, E CNPJ, F FECHAMENTO,
  // G SIMULADOR (link), H LINK THREAD, I OPORTUNIDADE, J ALUNADO, K ACV, L MARCAS INVIABILIDADE,
  // M LINK DO PIC, N VERSÃO DO PIC.  (layout antigo: ABERTURA 1, FRENTE 2, MARCA 3, CONSULTOR 4, CNPJ 8, LINK 32)
  COL_ABERTURA: 6,                 // FECHAMENTO: define o pedido "mais recente"
  COL_FRENTE: 1, COL_MARCA: 2, COL_CONSULTOR: 3, COL_CNPJ: 5, COL_LINK: 7,
  COL_LINK_PIC: 13, COL_VERSAO_PIC: 14,
  LIMITE_MS: 4.5 * 60 * 1000,      // tempo de cada rodada
  SALVAR_A_CADA: 20,               // registros
  PROGRESSO_A_CADA: 50,            // linhas percorridas
  TRAVA_MS: 7 * 60 * 1000,         // evita duas rodadas ao mesmo tempo
  FUSO: 'America/Sao_Paulo',
  CAB_LOG: ['Linha (Aprovacoes)', 'Link', 'Problema'],
};

const CRESC = { ABA: 'Simulador', INI: 38, FIM: 57 };
const RESUMO = {
  ABA: 'Resumo da negociação',
  COL_ROTULO: 2,                    // coluna B: texto procurado
  ROTULO: 'bonificacao de material', // sem acento/maiúscula; basta a célula conter o texto
  COL_VALOR: 4,                     // coluna D: precisa ser > 0
};
const MAT = {                       // Renovação: aba "Material opcional"
  ABA: 'Material opcional',
  REN: { col: 20, ini: 19, fim: 87, cabLinha: 18 },   // coluna T
  AMP: { col: 15, ini: 94, fim: 112, cabLinha: 93 },  // coluna O
  CAB_ESPERADO: 'input final',
  COL_ID_MATERIAL: 0,               // coluna do ID do material (0 = não existe: sai vazio)
};
const B2C = {                       // Simulador antigo: aba Simulador, coluna W
  ABA: 'Simulador', COL: 23, INI: 23, FIM: 40,          // 17 séries + linha de controle; linhas sem preço > 0 são ignoradas
  CAB: { ini: 15, fim: 22, texto: 'b2c' },
};
const CAB_POT = ['Origem / segmento', 'Série', 'ID do material', 'Material', 'Preço B2C potencializador', 'Linha no simulador'];
const CAB_PRE = ['Link do simulador', 'CNPJ', 'Link do PIC', 'Versão do PIC', 'Marca', 'Frente', 'Consultor',
  'Texto encontrado (col. B)', 'Valor (col. D)', 'Linha no Resumo', 'Preços encontrados'];
const CAB_BASE = ['Link do simulador', 'CNPJ', 'Link do PIC', 'Versão do PIC', 'Marca', 'Frente', 'Consultor'];
const JOBS = {
  cresc: {
    id: 'cresc', titulo: 'Crescimento (preço família)', handler: 'processar', propProx: 'proxima',
    abaResult: 'Resultado_Crescimento', abaLog: 'Log_Crescimento',
    cabResult: ['Link do simulador', 'CNPJ', 'Link do PIC', 'Versão do PIC', 'Marca', 'Frente', 'Consultor', 'Série', 'Preço de tabela', 'Desconto',
      'Preço negociado', 'Preço família'],
    csvPrefixo: 'preco_familia_simuladores_', ler: lerCrescimento_,
  },
  mat: {
    id: 'mat', titulo: 'Renovação (potencializador)', handler: 'processarMat', propProx: 'proxima_mat',
    abaResult: 'Resultado_Renovação', abaLog: 'Log_Renovação', abaPre: 'Bonificados_Renovação',
    cabResult: CAB_BASE.concat(CAB_POT), cabPre: CAB_PRE,
    csvPrefixo: 'renovacao_potencializador_', ler: lerRenovacao_,
  },
  b2c: {
    id: 'b2c', titulo: 'Simulador antigo (potencializador)', handler: 'processarB2C', propProx: 'proxima_b2c',
    abaResult: 'Resultado_SimuladorAntigo', abaLog: 'Log_SimuladorAntigo', abaPre: 'Bonificados_SimuladorAntigo',
    cabResult: CAB_BASE.concat(CAB_POT), cabPre: CAB_PRE,
    csvPrefixo: 'simulador_antigo_potencializador_', ler: lerSimuladorAntigo_,
  },
};

// ===================== MENU E PAINEL =====================
function onOpen() {
  SpreadsheetApp.getUi().createMenu('Simulador')
    .addItem('Abrir painel de progresso', 'abrirPainel')
    .addSeparator()
    .addItem('Recomeçar do zero: Crescimento (preço família)', 'iniciar')
    .addItem('Recomeçar do zero: Renovação', 'iniciarMat')
    .addItem('Recomeçar do zero: Simulador antigo', 'iniciarB2C')
    .addToUi();
}

function abrirPainel() {
  const html = HtmlService.createHtmlOutputFromFile('Painel').setTitle('Progresso das extrações');
  SpreadsheetApp.getUi().showSidebar(html);
}

// ===================== PONTOS DE ENTRADA (nomes usados pelos gatilhos) =====================
function processar() { return rodar_(JOBS.cresc); }
function processarMat() { return rodar_(JOBS.mat); }
function processarB2C() { return rodar_(JOBS.b2c); }

function iniciar() { confirmarEIniciar_(JOBS.cresc); }
function iniciarMat() { confirmarEIniciar_(JOBS.mat); }
function iniciarB2C() { confirmarEIniciar_(JOBS.b2c); }

function confirmarEIniciar_(job) {
  const ui = SpreadsheetApp.getUi();
  const r = ui.alert('Recomeçar do zero?',
    'Isso apaga o que foi coletado em ' + abasDoJob_(job).map(function (n) { return '"' + n + '"'; }).join(', ') +
    ' e começa de novo.\n' +
    'Uma cópia de segurança dessas abas será criada antes.\n\nContinuar?', ui.ButtonSet.YES_NO);
  if (r === ui.Button.YES) iniciarDoZero_(job);
}

// ===================== FUNÇÕES CHAMADAS PELO PAINEL =====================
function statusPainel() {
  const ss = SpreadsheetApp.getActive();
  const apr = ss.getSheetByName(GERAL.ABA_APROVACOES);
  const total = apr ? Math.max(0, apr.getLastRow() - 1) : 0;
  const props = PropertiesService.getScriptProperties();
  const gatilhos = ScriptApp.getProjectTriggers().map(function (t) { return t.getHandlerFunction(); });
  const agora = Date.now();
  return Object.keys(JOBS).map(function (k) {
    const job = JOBS[k];
    const st = lerEstado_(job);
    const prox = parseInt(props.getProperty(job.propProx) || '0', 10);
    const res = ss.getSheetByName(job.abaResult), log = ss.getSheetByName(job.abaLog);
    const cont = { semAcesso: 0, inconsistente: 0, erro: 0, divergencia: 0, outros: 0 };
    let nLog = 0;
    if (log && log.getLastRow() > 1) {
      log.getRange(2, 3, log.getLastRow() - 1, 1).getValues().forEach(function (v) {
        const t = String(v[0]); nLog++;
        if (t.indexOf('SEM ACESSO') === 0) cont.semAcesso++;
        else if (t.indexOf('PLANILHA INCONSISTENTE') === 0) cont.inconsistente++;
        else if (t.indexOf('ERRO') === 0) cont.erro++;
        else if (t.indexOf('DIVERGÊNCIA') === 0) cont.divergencia++;
        else cont.outros++;
      });
    }
    const temGatilho = gatilhos.indexOf(job.handler) >= 0;
    let fase = st.fase;
    if (!fase) fase = (total > 0 && prox >= total) ? 'concluido' : (temGatilho ? 'aguardando' : 'sem_atividade');
    let eta = null;
    if (st.iniciadoEm && fase !== 'concluido' && prox > (st.prox0 || 0) && agora - st.iniciadoEm > 120000) {
      const taxa = (prox - (st.prox0 || 0)) / (agora - st.iniciadoEm);
      eta = Math.round((total - prox) / taxa / 60000); // minutos
    }
    return {
      id: job.id, titulo: job.titulo, fase: fase, total: total, prox: Math.min(prox, total),
      pct: total > 0 ? Math.min(100, Math.round(prox / total * 100)) : 0,
      resultados: res ? Math.max(0, res.getLastRow() - 1) : 0,
      bonificados: job.abaPre ? (function () { const p = ss.getSheetByName(job.abaPre); return p ? Math.max(0, p.getLastRow() - 1) : 0; })() : null,
      log: cont, nLog: nLog, gatilho: temGatilho,
      segDesdeAtividade: st.atualizadoEm ? Math.round((agora - st.atualizadoEm) / 1000) : null,
      etaMin: eta, csvUrl: st.csvUrl || '', erro: st.erro || '',
      abasOk: !!res && !!log && (!job.abaPre || !!ss.getSheetByName(job.abaPre)), abaResult: job.abaResult,
    };
  });
}

function csvParcial(id) {
  const job = JOBS[id];
  const csv = montarCsv_(job);
  return { nome: job.csvPrefixo + 'PARCIAL_' + carimbo_() + '.csv', csv: '﻿' + csv.texto, linhas: csv.linhas };
}

function salvarNoDrive(id) {
  return { url: gerarCsvDrive_(JOBS[id]) };
}

function retomar(id) {
  const job = JOBS[id];
  PropertiesService.getScriptProperties().deleteProperty('parar_' + id);
  const r = rodar_(job);
  return { resultado: r || 'ok' };
}

function parar(id) {
  const job = JOBS[id];
  const props = PropertiesService.getScriptProperties();
  props.setProperty('parar_' + id, '1');
  apagarGatilhos_(job);
  const emExecucao = Date.now() - Number(props.getProperty('trava_' + id) || 0) < GERAL.TRAVA_MS;
  if (!emExecucao) {
    const st = lerEstado_(job); st.fase = 'parado'; st.atualizadoEm = Date.now(); salvarEstado_(job, st);
    props.deleteProperty('parar_' + id);
  }
  return { emExecucao: emExecucao };
}

// ===================== MOTOR =====================
function rodar_(job) {
  const t0 = Date.now();
  const props = PropertiesService.getScriptProperties();
  const cnpjs = lerCnpjs_();
  if (GERAL.FILTRAR_CNPJ && cnpjs.size === 0) {
    const st0 = lerEstado_(job);
    st0.fase = 'erro'; st0.atualizadoEm = Date.now();
    st0.erro = 'Lista de CNPJs vazia: preencha a aba "' + GERAL.ABA_CNPJS + '" (coluna A, a partir da linha 2).';
    salvarEstado_(job, st0);
    apagarGatilhos_(job);
    return 'sem_cnpj';
  }
  const chaveTrava = 'trava_' + job.id;
  const desde = Number(props.getProperty(chaveTrava) || 0);
  if (desde && t0 - desde < GERAL.TRAVA_MS) { agendar_(job, 2 * 60 * 1000); return 'ocupado'; }
  props.setProperty(chaveTrava, String(t0));

  const ss = SpreadsheetApp.getActive();
  const res = prepararAba_(ss, job.abaResult, job.cabResult);
  const log = prepararAba_(ss, job.abaLog, GERAL.CAB_LOG);
  const pre = job.abaPre ? prepararAba_(ss, job.abaPre, job.cabPre) : null;
  const bufRes = [], bufLog = [], bufPre = [];
  const st = lerEstado_(job);
  let i = parseInt(props.getProperty(job.propProx) || '0', 10);
  let ultimoSalvo = i;
  let parado = false;

  const salvar = function () {
    if (bufRes.length) { res.getRange(res.getLastRow() + 1, 1, bufRes.length, job.cabResult.length).setValues(bufRes); bufRes.length = 0; }
    if (bufPre.length) { pre.getRange(pre.getLastRow() + 1, 1, bufPre.length, job.cabPre.length).setValues(bufPre); bufPre.length = 0; }
    if (bufLog.length) { log.getRange(log.getLastRow() + 1, 1, bufLog.length, 3).setValues(bufLog); bufLog.length = 0; }
    props.setProperty(job.propProx, String(i));
    ultimoSalvo = i;
    st.fase = 'rodando'; st.atualizadoEm = Date.now();
    salvarEstado_(job, st);
    if (props.getProperty('parar_' + job.id)) parado = true;
  };

  try {
    // rede de segurança: se esta rodada falhar, uma nova tentativa acontece em 8 min
    agendar_(job, 8 * 60 * 1000);
    if (!st.iniciadoEm) { st.iniciadoEm = Date.now(); st.prox0 = i; }
    st.erro = ''; st.fase = 'rodando'; st.atualizadoEm = Date.now(); salvarEstado_(job, st);

    const aba = ss.getSheetByName(GERAL.ABA_APROVACOES);
    if (!aba) throw new Error('Aba "' + GERAL.ABA_APROVACOES + '" não encontrada');
    const ultima = aba.getLastRow();
    const dados = ultima > 1 ? aba.getRange(2, 1, ultima - 1, GERAL.COL_LINK).getValues() : [];
    const rich = ultima > 1 ? aba.getRange(2, GERAL.COL_LINK, ultima - 1, 1).getRichTextValues() : [];

    // links já processados (dedupe e retomada)
    const vistos = new Set();
    [[res, 1], [log, 2], [pre, 1]].forEach(function (p) {
      if (!p[0]) return;
      const n = p[0].getLastRow() - 1;
      if (n > 0) p[0].getRange(2, p[1], n, 1).getValues().forEach(function (r) { vistos.add(String(r[0])); });
    });

    // link repetido: vale só o pedido MAIS RECENTE
    const vencedor = escolherVencedores_(aba, dados, rich, cnpjs);

    for (; i < dados.length; i++) {
      if (parado || Date.now() - t0 > GERAL.LIMITE_MS) break;
      if (bufRes.length + bufLog.length + bufPre.length >= GERAL.SALVAR_A_CADA || i - ultimoSalvo >= GERAL.PROGRESSO_A_CADA) {
        salvar();
        if (parado) break;
      }
      const linhaPlan = i + 2;
      let link = '';
      try {
        const l = dados[i];
        if (!dentroDoPeriodo_(l[GERAL.COL_ABERTURA - 1])) continue;
        if (GERAL.FILTRAR_CNPJ && !cnpjs.has(normCnpj_(l[GERAL.COL_CNPJ - 1]))) continue; // só os CNPJs da lista
        link = extrairLink_(l[GERAL.COL_LINK - 1], rich[i][0]);
        if (!link) continue;
        if (aba.isRowHiddenByFilter(linhaPlan) || aba.isRowHiddenByUser(linhaPlan)) continue; // só linhas visíveis
        if (vencedor.get(link) !== i) continue; // há um pedido mais recente com o mesmo link
        if (vistos.has(link)) continue;
        vistos.add(link);
        const id = idDoLink_(link);
        if (!id) { bufLog.push([linhaPlan, link, 'Link inválido']); continue; }
        let planilha;
        try {
          planilha = SpreadsheetApp.openById(id);
        } catch (e) {
          bufLog.push([linhaPlan, link, 'SEM ACESSO (' + String(e.message).slice(0, 120) + ')']);
          continue;
        }
        const out = job.ler(planilha, l, link);
        out.linhas.forEach(function (r) { bufRes.push(r); });
        (out.pre || []).forEach(function (r) { bufPre.push(r); });
        out.logs.forEach(function (m) { bufLog.push([linhaPlan, link, m]); });
      } catch (e) {
        bufLog.push([linhaPlan, link, 'ERRO: ' + e.message]);
      }
    }
    salvar();

    apagarGatilhos_(job); // remove a rede de segurança
    if (parado || props.getProperty('parar_' + job.id)) {
      props.deleteProperty('parar_' + job.id);
      st.fase = 'parado'; st.atualizadoEm = Date.now(); salvarEstado_(job, st);
      return 'parado';
    }
    if (i < dados.length) {
      agendar_(job, 60 * 1000);
      st.fase = 'aguardando'; st.atualizadoEm = Date.now(); salvarEstado_(job, st);
      return 'aguardando';
    }
    if (GERAL.FILTRAR_CNPJ) registrarCnpjsSemPedido_(log, cnpjs, dados);
    st.fase = 'concluido'; st.atualizadoEm = Date.now();
    st.csvUrl = gerarCsvDrive_(job);
    salvarEstado_(job, st);
    return 'concluido';
  } catch (e) {
    try { st.fase = 'erro'; st.erro = String(e.message).slice(0, 300); st.atualizadoEm = Date.now(); salvarEstado_(job, st); } catch (e2) {}
    throw e; // a execução aparece como falha, mas a rede de segurança já reagendou
  } finally {
    props.deleteProperty(chaveTrava);
  }
}

function abasDoJob_(job) {
  return [job.abaResult, job.abaLog].concat(job.abaPre ? [job.abaPre] : []);
}

function iniciarDoZero_(job) {
  const ss = SpreadsheetApp.getActive();
  const props = PropertiesService.getScriptProperties();
  const sel = carimbo_();
  abasDoJob_(job).forEach(function (nome) {
    const sh = ss.getSheetByName(nome);
    if (sh && sh.getLastRow() > 1) {
      try { sh.copyTo(ss).setName(('Bkp_' + sel + '_' + nome).slice(0, 99)); } catch (e) {}
    }
  });
  apagarGatilhos_(job);
  props.deleteProperty('parar_' + job.id);
  props.deleteProperty('trava_' + job.id);
  props.setProperty(job.propProx, '0');
  salvarEstado_(job, { fase: 'rodando', iniciadoEm: Date.now(), prox0: 0, atualizadoEm: Date.now() });
  [[job.abaResult, job.cabResult], [job.abaLog, GERAL.CAB_LOG]].concat(job.abaPre ? [[job.abaPre, job.cabPre]] : []).forEach(function (p) {
    const sh = ss.getSheetByName(p[0]) || ss.insertSheet(p[0]);
    sh.clear();
    sh.getRange(1, 1, 1, p[1].length).setValues([p[1]]);
  });
  return rodar_(job);
}

// ===================== LEITORES (um por cenário; UMA LINHA POR SÉRIE/MATERIAL, sem concatenar) =====================
/** Colunas comuns: link do simulador, CNPJ, link e versão do PIC, marca, frente, consultor. */
function baseRow_(l, link, marca) {
  return [link, normCnpj_(l[GERAL.COL_CNPJ - 1]), l[GERAL.COL_LINK_PIC - 1], l[GERAL.COL_VERSAO_PIC - 1],
    marca || l[GERAL.COL_MARCA - 1], l[GERAL.COL_FRENTE - 1], l[GERAL.COL_CONSULTOR - 1]];
}

function lerCrescimento_(planilha, l, link) {
  const out = { linhas: [], logs: [] };
  const sim = planilha.getSheetByName(CRESC.ABA);
  if (!sim) { out.logs.push('PLANILHA INCONSISTENTE: aba "' + CRESC.ABA + '" não encontrada'); return out; }
  const n = CRESC.FIM - CRESC.INI + 1;
  const faixa = sim.getRange(CRESC.INI, 2, n, 6); // B..G
  const vals = faixa.getValues();
  const disp = faixa.getDisplayValues();
  for (let r = 0; r < n; r++) {
    if (!(numPositivo_(vals[r][5]) > 0)) continue; // só maior que zero
    out.linhas.push(baseRow_(l, link).concat([disp[r][0], disp[r][2], disp[r][3], disp[r][4], disp[r][5]]));
  }
  return out;
}

/**
 * Etapa a (pré-filtro), aba "Resumo da negociação": toda célula da coluna B que contém
 * "Bonificação de material" com valor > 0 na coluna D.
 * Devolve { aba, achou, itens: [{rotulo, valor, linha}], erros }.
 */
function lerResumo_(planilha) {
  const out = { aba: true, achou: false, itens: [], erros: [] };
  const aba = achaAba_(planilha, RESUMO.ABA);
  if (!aba) { out.aba = false; return out; }
  const ultima = aba.getLastRow();
  if (ultima < 1) return out;
  const faixa = aba.getRange(1, 1, ultima, Math.max(RESUMO.COL_ROTULO, RESUMO.COL_VALOR));
  const vals = faixa.getValues(), disp = faixa.getDisplayValues();
  let comErro = 0;
  for (let r = 0; r < vals.length; r++) {
    const rotulo = String(disp[r][RESUMO.COL_ROTULO - 1]).trim();
    if (norm_(rotulo).indexOf(RESUMO.ROTULO) < 0) continue;
    out.achou = true;
    const bruto = vals[r][RESUMO.COL_VALOR - 1];
    if (String(bruto).charAt(0) === '#') { comErro++; continue; }
    const valor = numPositivo_(bruto);
    if (valor > 0) out.itens.push({ rotulo: rotulo, valor: valor, linha: r + 1 });
  }
  if (comErro) out.erros.push('PLANILHA INCONSISTENTE: ' + comErro + ' célula(s) com erro (#REF! etc.) na coluna D de "Bonificação de material"');
  return out;
}

/** Renovação: pré-filtro + preços da aba "Material opcional". */
function lerRenovacao_(planilha, l, link) { return lerPotencializador_(planilha, l, link, lerPrecoMat_); }
/** Simulador antigo: pré-filtro + preços da aba Simulador, coluna W. */
function lerSimuladorAntigo_(planilha, l, link) { return lerPotencializador_(planilha, l, link, lerPrecoB2C_); }

function lerPotencializador_(planilha, l, link, lerPreco) {
  const out = { linhas: [], pre: [], logs: [] };
  const rs = lerResumo_(planilha);
  if (!rs.aba) { out.logs.push('PLANILHA INCONSISTENTE: aba "' + RESUMO.ABA + '" não encontrada'); return out; }
  if (!rs.achou) {
    out.logs.push('PLANILHA INCONSISTENTE: célula "Bonificação de material" não encontrada na coluna B da aba "' + RESUMO.ABA + '"');
    return out;
  }
  rs.erros.forEach(function (m) { out.logs.push(m); });
  if (!rs.itens.length) return out; // sem material bonificado: não é potencializador

  let precos = null;
  if (!GERAL.SO_PREFILTRO) {
    precos = lerPreco(planilha);
    precos.erros.forEach(function (m) { out.logs.push('PLANILHA INCONSISTENTE: ' + m); });
    precos.itens.forEach(function (p) {
      out.linhas.push(baseRow_(l, link, p.marca).concat([p.origem, p.serie, p.id, p.material, p.preco, p.linha]));
    });
    if (!precos.itens.length && !precos.erros.length) {
      out.logs.push('DIVERGÊNCIA: "Bonificação de material" > 0 no Resumo, mas nenhum preço > 0 na aba de preços');
    }
  }
  const status = precos ? (precos.itens.length ? 'Sim (' + precos.itens.length + ')' : 'Não') : 'Não verificado';
  rs.itens.forEach(function (it) {
    out.pre.push(baseRow_(l, link).concat([it.rotulo, it.valor, it.linha, status]));
  });
  return out;
}

/** Etapa b da Renovação: itens com preço > 0 em "Material opcional" (col. T e col. O). */
function lerPrecoMat_(planilha) {
  const out = { itens: [], erros: [] };
  const aba = achaAba_(planilha, MAT.ABA);
  if (!aba) { out.erros.push('aba "' + MAT.ABA + '" não encontrada'); return out; }
  [[MAT.REN, 'Renovação', 'Renovação (col. T)'], [MAT.AMP, 'Ampliação', 'Ampliação (col. O)']].forEach(function (s) {
    const cfg = s[0];
    const cab = String(aba.getRange(cfg.cabLinha, cfg.col).getDisplayValue());
    if (norm_(cab).indexOf(MAT.CAB_ESPERADO) < 0) {
      out.erros.push(s[2] + ': cabeçalho esperado "Input final do contrato" não encontrado na linha ' +
        cfg.cabLinha + ' (encontrado: "' + cab.slice(0, 60) + '")');
      return;
    }
    const n = cfg.fim - cfg.ini + 1;
    const vals = aba.getRange(cfg.ini, 1, n, Math.max(cfg.col, MAT.COL_ID_MATERIAL)).getDisplayValues();
    const limpa = function (x) { x = String(x || '').trim(); return x.charAt(0) === '#' ? '' : x; };
    let comErro = 0;
    for (let r = 0; r < n; r++) {
      const v = String(vals[r][cfg.col - 1]).trim();
      if (v === '') continue;
      if (v.charAt(0) === '#') { comErro++; continue; }
      if (!(numPositivo_(v) > 0)) continue; // só maior que zero
      out.itens.push({
        origem: s[1],
        marca: limpa(vals[r][1]),                                              // B
        serie: limpa(vals[r][3]),                                              // D
        id: MAT.COL_ID_MATERIAL ? limpa(vals[r][MAT.COL_ID_MATERIAL - 1]) : '',
        material: limpa(vals[r][4]) || limpa(vals[r][0]) || '(sem material)',  // E, senão A
        preco: numPositivo_(v),
        linha: cfg.ini + r,
      });
    }
    if (comErro) out.erros.push(s[2] + ': ' + comErro + ' célula(s) com erro (#REF! etc.)');
  });
  return out;
}

/** Etapa b do Simulador antigo: séries com preço de venda B2C > 0 na coluna W. */
function lerPrecoB2C_(planilha) {
  const out = { itens: [], erros: [] };
  const sim = planilha.getSheetByName(B2C.ABA);
  if (!sim) { out.erros.push('aba "' + B2C.ABA + '" não encontrada'); return out; }
  const b = B2C.CAB;
  const cabs = sim.getRange(b.ini, B2C.COL, b.fim - b.ini + 1, 1).getDisplayValues();
  if (!cabs.some(function (r) { return norm_(r[0]).indexOf(b.texto) >= 0; })) {
    out.erros.push('cabeçalho "Preço de venda B2C" não encontrado na coluna W (linhas ' + b.ini + '-' + b.fim + ')');
    return out;
  }
  const n = B2C.FIM - B2C.INI + 1;
  const faixa = sim.getRange(B2C.INI, 1, n, B2C.COL); // A..W
  const vals = faixa.getValues(), disp = faixa.getDisplayValues();
  let comErro = 0;
  for (let r = 0; r < n; r++) {
    const bruto = vals[r][B2C.COL - 1];
    if (bruto === '' || bruto === null) continue;
    if (String(bruto).charAt(0) === '#') { comErro++; continue; }
    if (!(numPositivo_(bruto) > 0)) continue; // só maior que zero
    out.itens.push({
      origem: String(disp[r][1]).trim(),                                       // segmento (B)
      marca: '',
      serie: String(disp[r][2]).trim(),                                        // série (C)
      id: '',
      material: String(disp[r][11]).trim() || String(disp[r][3]).trim(),       // L (col. 27), senão D (material 26)
      preco: numPositivo_(bruto),
      linha: B2C.INI + r,
    });
  }
  if (comErro) out.erros.push(comErro + ' célula(s) com erro (#REF! etc.) na coluna W');
  return out;
}

// ===================== CSV =====================
function montarCsv_(job) {
  const sh = SpreadsheetApp.getActive().getSheetByName(job.abaResult);
  const linhas = sh && sh.getLastRow() > 0 ? sh.getDataRange().getDisplayValues() : [job.cabResult];
  const texto = linhas.map(function (r) {
    return r.map(function (c) { return '"' + String(c).replace(/"/g, '""') + '"'; }).join(',');
  }).join('\n');
  return { texto: texto, linhas: Math.max(0, linhas.length - 1) };
}

function gerarCsvDrive_(job) {
  const csv = montarCsv_(job);
  const arq = DriveApp.createFile(job.csvPrefixo + carimbo_() + '.csv', '﻿' + csv.texto, MimeType.CSV);
  return arq.getUrl();
}

// ===================== UTILITÁRIOS =====================
function lerEstado_(job) {
  try { return JSON.parse(PropertiesService.getScriptProperties().getProperty('estado_' + job.id) || '{}'); }
  catch (e) { return {}; }
}
function salvarEstado_(job, st) {
  PropertiesService.getScriptProperties().setProperty('estado_' + job.id, JSON.stringify(st));
}
function prepararAba_(ss, nome, cab) {
  const sh = ss.getSheetByName(nome) || ss.insertSheet(nome);
  if (sh.getLastRow() === 0) sh.getRange(1, 1, 1, cab.length).setValues([cab]);
  return sh;
}
function agendar_(job, ms) {
  apagarGatilhos_(job);
  ScriptApp.newTrigger(job.handler).timeBased().after(ms).create();
}
function apagarGatilhos_(job) {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === job.handler) ScriptApp.deleteTrigger(t);
  });
}
function carimbo_() { return Utilities.formatDate(new Date(), GERAL.FUSO, 'yyyyMMdd_HHmmss'); }

/** Número ou texto pt-BR ("R$ 2.742,00") vira número; texto que não é número vira NaN. */
function numPositivo_(v) {
  if (typeof v === 'number') return v;
  const s = String(v).trim();
  if (!/^(R\$\s*)?-?[\d.,]+$/.test(s)) return NaN;
  return parseFloat(s.replace(/^R\$\s*/, '').replace(/\./g, '').replace(',', '.'));
}
function norm_(t) {
  return String(t || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').trim();
}
function achaAba_(planilha, nome) {
  const alvo = norm_(nome);
  const abas = planilha.getSheets();
  for (let k = 0; k < abas.length; k++) if (norm_(abas[k].getName()) === alvo) return abas[k];
  return null;
}
function dentroDoPeriodo_(v) {
  if (!GERAL.DATA_INICIO) return true; // qualquer data
  let d = v;
  if (!(d instanceof Date)) {
    const m = String(v).match(/(\d{1,2})\/(\d{1,2})\/(\d{4})/);
    if (!m) return false;
    d = new Date(+m[3], +m[2] - 1, +m[1]);
  }
  return d >= GERAL.DATA_INICIO;
}
/** Data/hora do pedido em milissegundos; sem data legível = muito antigo. */
function tempoPedido_(v) {
  if (v instanceof Date) return v.getTime();
  const m = String(v).match(/(\d{1,2})\/(\d{1,2})\/(\d{4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?/);
  if (!m) return -Infinity;
  return new Date(+m[3], +m[2] - 1, +m[1], +(m[4] || 0), +(m[5] || 0), +(m[6] || 0)).getTime();
}
/** Para cada link, o índice do pedido mais recente (empate: o que está mais abaixo na aba). */
function escolherVencedores_(aba, dados, rich, cnpjs) {
  const grupos = new Map();
  dados.forEach(function (l, i) {
    if (!dentroDoPeriodo_(l[GERAL.COL_ABERTURA - 1])) return;
    if (GERAL.FILTRAR_CNPJ && !cnpjs.has(normCnpj_(l[GERAL.COL_CNPJ - 1]))) return;
    const link = extrairLink_(l[GERAL.COL_LINK - 1], rich[i][0]);
    if (!link) return;
    if (!grupos.has(link)) grupos.set(link, []);
    grupos.get(link).push(i);
  });
  const vencedor = new Map();
  grupos.forEach(function (idx, link) {
    let cand = idx;
    if (idx.length > 1) { // só confere filtro nos links repetidos
      cand = idx.filter(function (i) { return !(aba.isRowHiddenByFilter(i + 2) || aba.isRowHiddenByUser(i + 2)); });
    }
    if (!cand.length) return;
    let melhor = cand[0], tm = tempoPedido_(dados[melhor][GERAL.COL_ABERTURA - 1]);
    cand.forEach(function (i) {
      const t = tempoPedido_(dados[i][GERAL.COL_ABERTURA - 1]);
      if (t >= tm) { melhor = i; tm = t; }
    });
    vencedor.set(link, melhor);
  });
  return vencedor;
}
/** Só os números do CNPJ, completando com zeros à esquerda até 14 dígitos. */
function normCnpj_(v) {
  const d = String(v == null ? '' : v).replace(/\D/g, '');
  return d ? ('00000000000000' + d).slice(-Math.max(14, d.length)) : '';
}
/** Lê a aba "CNPJs" (coluna A, linha 2 em diante). */
function lerCnpjs_() {
  const out = new Set();
  const sh = SpreadsheetApp.getActive().getSheetByName(GERAL.ABA_CNPJS);
  if (!sh || sh.getLastRow() < 2) return out;
  sh.getRange(2, 1, sh.getLastRow() - 1, 1).getDisplayValues().forEach(function (r) {
    const c = normCnpj_(r[0]); if (c) out.add(c);
  });
  return out;
}
/** Avisa no log quais CNPJs da lista não aparecem em nenhum pedido (ajuda a achar erro de digitação). */
function registrarCnpjsSemPedido_(log, cnpjs, dados) {
  const presentes = new Set(dados.map(function (r) { return normCnpj_(r[GERAL.COL_CNPJ - 1]); }));
  const existentes = new Set();
  if (log.getLastRow() > 1) log.getRange(2, 3, log.getLastRow() - 1, 1).getValues().forEach(function (v) { existentes.add(String(v[0])); });
  const novos = [];
  cnpjs.forEach(function (c) {
    const msg = 'AVISO: CNPJ da lista sem nenhum pedido na aba Aprovacoes: ' + c;
    if (!presentes.has(c) && !existentes.has(msg)) novos.push(['', '', msg]);
  });
  if (novos.length) log.getRange(log.getLastRow() + 1, 1, novos.length, 3).setValues(novos);
}
function extrairLink_(valor, rich) {
  const m = String(valor || '').match(/https?:\/\/\S+/);
  if (m) return m[0];
  return (rich && rich.getLinkUrl()) || '';
}
function idDoLink_(url) {
  const m = url.match(/\/d\/([a-zA-Z0-9_-]+)/) || url.match(/[?&]id=([a-zA-Z0-9_-]+)/);
  return m ? m[1] : null;
}
