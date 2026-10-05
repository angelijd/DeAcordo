/**
 * EXTRAÇÕES DE SIMULADORES (4 cenários) + PAINEL DE PROGRESSO
 *
 *  1) Crescimento  : aba Simulador, col. G, linhas 38-57, valor > 0
 *  2) Renovação/ampliação: aba "Material opcional", col. T (19-87) e col. O (94-112), valor > 0
 *  3) Preço B2C    : aba Simulador, col. W, linhas 23-37, valor > 0
 *  4) Potencializadores (B2C): mesma leitura do cenário 2, mas UMA LINHA POR MATERIAL,
 *     com CNPJ, link/versão do PIC, marca, série, material e preço; só o simulador mais
 *     recente por CNPJ + marca.
 *
 * Regras comuns: pedidos de QUALQUER data cujo CNPJ (col. H da Aprovacoes) esteja na aba
 * "CNPJs" (col. A, a partir da linha 2); só linhas visíveis; link na col. AF;
 * sem acesso => pula e registra no log (com o consultor); uma linha por simulador.
 * Link repetido: vale o pedido mais recente (data/hora da col. A).
 *
 * Tudo que é coletado é gravado nas abas de resultado a cada poucos registros e o
 * ponto onde parou é salvo junto: se algo falhar, a próxima rodada continua dali.
 * Menu "Simulador" > "Abrir painel de progresso" mostra tudo ao vivo.
 */

// ===================== CONFIGURAÇÃO (mude os nomes das abas aqui) =====================
const GERAL = {
  ABA_APROVACOES: 'Aprovacoes',
  DATA_INICIO: null,               // null = qualquer data (ou new Date(2026, 8, 1) para filtrar)
  FILTRAR_CNPJ: true,              // só pedidos cujo CNPJ está na aba abaixo
  ABA_CNPJS: 'CNPJs',              // lista de CNPJs: coluna A, a partir da linha 2
  // Colunas da aba Aprovacoes: A FRENTE, B MARCA(S), C SOLICITANTE, D REDE, E CNPJ, F FECHAMENTO,
  // G SIMULADOR (link), H LINK THREAD, I OPORTUNIDADE, J ALUNADO, K ACV, L MARCAS INVIABILIDADE,
  // M LINK DO PIC, N VERSÃO DO PIC.   (layout antigo: ABERTURA 1, FRENTE 2, MARCA 3, CONSULTOR 4, CNPJ 8, LINK 32)
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
const MAT = {
  ABA: 'Material opcional',
  REN: { col: 20, ini: 19, fim: 87, cabLinha: 18 },   // coluna T
  AMP: { col: 15, ini: 94, fim: 112, cabLinha: 93 },  // coluna O
  CAB_ESPERADO: 'input final',
};
const B2C = {
  ABA: 'Simulador', COL: 23, INI: 23, FIM: 37,          // coluna W
  CAB: { ini: 15, fim: 22, texto: 'b2c' },
};
// Potencializadores: usa as mesmas faixas de MAT, uma linha por material.
const POT = {
  INCLUIR_AMPLIACAO: true,        // false = só renovação (col. T)
  COL_ID_MATERIAL: 0,             // coluna do ID do material em "Material opcional" (0 = não existe)
  CABS_ACEITOS: ['input final', 'b2c', 'revenda'],  // texto esperado no cabeçalho da coluna de preço
};

const JOBS = {
  cresc: {
    id: 'cresc', titulo: 'Crescimento (preço família)', handler: 'processar', propProx: 'proxima',
    abaResult: 'Resultado_Crescimento', abaLog: 'Log_Crescimento',
    cabResult: ['Link do simulador', 'Consultor', 'Frente', 'Séries', 'Preço de tabela', 'Desconto',
      'Preço negociado', 'Preço família', 'Marca'],
    csvPrefixo: 'preco_familia_simuladores_', ler: lerCrescimento_,
  },
  mat: {
    id: 'mat', titulo: 'Renovação e ampliação (material opcional)', handler: 'processarMat', propProx: 'proxima_mat',
    abaResult: 'Resultado_Renovação', abaLog: 'Log_Renovação',
    cabResult: ['Link do simulador', 'Consultor', 'Frente', 'Material de renovação', 'Material de ampliação', 'Marca'],
    csvPrefixo: 'material_opcional_', ler: lerMaterial_,
  },
  b2c: {
    id: 'b2c', titulo: 'Preço de venda B2C', handler: 'processarB2C', propProx: 'proxima_b2c',
    abaResult: 'Resultado_Renovação_SimuladorAntigo', abaLog: 'Log_Renovação_SimuladorAntigo',
    cabResult: ['Link do simulador', 'Consultor', 'Frente', 'Marca', 'Segmentos', 'Séries',
      'Material col. 27', 'Preço de venda B2C'],
    csvPrefixo: 'preco_b2c_simuladores_', ler: lerB2C_,
  },
  pot: {
    id: 'pot', titulo: 'Potencializadores (preço B2C por material)', handler: 'processarPot', propProx: 'proxima_pot',
    abaResult: 'Resultado_Potencializadores', abaLog: 'Log_Potencializadores',
    cabResult: ['Link do simulador', 'CNPJ', 'Link do PIC', 'Versão do PIC', 'Marca', 'Frente',
      'Origem', 'Série', 'ID do material', 'Material', 'Preço B2C potencializador', 'Consultor'],
    csvPrefixo: 'potencializadores_b2c_', ler: lerPot_,
    chaveDedupe: function (l) { return normCnpj_(l[GERAL.COL_CNPJ - 1]) + '|' + norm_(l[GERAL.COL_MARCA - 1]); },
  },
};

// ===================== MENU E PAINEL =====================
function onOpen() {
  SpreadsheetApp.getUi().createMenu('Simulador')
    .addItem('Abrir painel de progresso', 'abrirPainel')
    .addSeparator()
    .addItem('Recomeçar do zero: Crescimento (preço família)', 'iniciar')
    .addItem('Recomeçar do zero: Material opcional (renovação/ampliação)', 'iniciarMat')
    .addItem('Recomeçar do zero: Preço B2C', 'iniciarB2C')
    .addItem('Recomeçar do zero: Potencializadores (B2C por material)', 'iniciarPot')
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
function processarPot() { return rodar_(JOBS.pot); }

function iniciar() { confirmarEIniciar_(JOBS.cresc); }
function iniciarMat() { confirmarEIniciar_(JOBS.mat); }
function iniciarB2C() { confirmarEIniciar_(JOBS.b2c); }
function iniciarPot() { confirmarEIniciar_(JOBS.pot); }

function confirmarEIniciar_(job) {
  const ui = SpreadsheetApp.getUi();
  const r = ui.alert('Recomeçar do zero?',
    'Isso apaga o que foi coletado em "' + job.abaResult + '" e "' + job.abaLog + '" e começa de novo.\n' +
    'Uma cópia de segurança das duas abas será criada antes.\n\nContinuar?', ui.ButtonSet.YES_NO);
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
    const cont = { semAcesso: 0, inconsistente: 0, erro: 0, outros: 0 };
    let nLog = 0;
    if (log && log.getLastRow() > 1) {
      log.getRange(2, 3, log.getLastRow() - 1, 1).getValues().forEach(function (v) {
        const t = String(v[0]); nLog++;
        if (t.indexOf('SEM ACESSO') === 0) cont.semAcesso++;
        else if (t.indexOf('PLANILHA INCONSISTENTE') === 0) cont.inconsistente++;
        else if (t.indexOf('ERRO') === 0) cont.erro++;
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
      log: cont, nLog: nLog, gatilho: temGatilho,
      segDesdeAtividade: st.atualizadoEm ? Math.round((agora - st.atualizadoEm) / 1000) : null,
      etaMin: eta, csvUrl: st.csvUrl || '', erro: st.erro || '',
      abasOk: !!res && !!log, abaResult: job.abaResult,
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
  const bufRes = [], bufLog = [];
  const st = lerEstado_(job);
  let i = parseInt(props.getProperty(job.propProx) || '0', 10);
  let ultimoSalvo = i;
  let parado = false;

  const salvar = function () {
    if (bufRes.length) { res.getRange(res.getLastRow() + 1, 1, bufRes.length, job.cabResult.length).setValues(bufRes); bufRes.length = 0; }
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
    [[res, 1], [log, 2]].forEach(function (p) {
      const n = p[0].getLastRow() - 1;
      if (n > 0) p[0].getRange(2, p[1], n, 1).getValues().forEach(function (r) { vistos.add(String(r[0])); });
    });

    // repetido (mesmo link, ou mesma chave do job, ex.: CNPJ + marca): vale só o pedido MAIS RECENTE
    const vencedor = escolherVencedores_(aba, dados, rich, cnpjs, job);

    for (; i < dados.length; i++) {
      if (parado || Date.now() - t0 > GERAL.LIMITE_MS) break;
      if (bufRes.length + bufLog.length >= GERAL.SALVAR_A_CADA || i - ultimoSalvo >= GERAL.PROGRESSO_A_CADA) {
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
        if (vencedor.get(chaveDe_(job, l, link)) !== i) continue; // há um pedido mais recente com a mesma chave
        if (vistos.has(link)) continue;
        vistos.add(link);
        const id = idDoLink_(link);
        if (!id) { bufLog.push([linhaPlan, link, 'Link inválido']); continue; }
        let planilha;
        try {
          planilha = SpreadsheetApp.openById(id);
        } catch (e) {
          bufLog.push([linhaPlan, link, 'SEM ACESSO (' + String(e.message).slice(0, 120) + ') | Consultor: ' +
            l[GERAL.COL_CONSULTOR - 1] + ' | CNPJ: ' + normCnpj_(l[GERAL.COL_CNPJ - 1])]);
          continue;
        }
        const out = job.ler(planilha, l, link);
        out.linhas.forEach(function (r) { bufRes.push(r); });
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

function iniciarDoZero_(job) {
  const ss = SpreadsheetApp.getActive();
  const props = PropertiesService.getScriptProperties();
  const sel = carimbo_();
  [job.abaResult, job.abaLog].forEach(function (nome) {
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
  [[job.abaResult, job.cabResult], [job.abaLog, GERAL.CAB_LOG]].forEach(function (p) {
    const sh = ss.getSheetByName(p[0]) || ss.insertSheet(p[0]);
    sh.clear();
    sh.getRange(1, 1, 1, p[1].length).setValues([p[1]]);
  });
  return rodar_(job);
}

// ===================== LEITORES (um por cenário) =====================
function baseRow_(l, link) {
  return [link, l[GERAL.COL_CONSULTOR - 1], l[GERAL.COL_FRENTE - 1]];
}

function lerCrescimento_(planilha, l, link) {
  const out = { linhas: [], logs: [] };
  const sim = planilha.getSheetByName(CRESC.ABA);
  if (!sim) { out.logs.push('PLANILHA INCONSISTENTE: aba "' + CRESC.ABA + '" não encontrada'); return out; }
  const n = CRESC.FIM - CRESC.INI + 1;
  const faixa = sim.getRange(CRESC.INI, 2, n, 6); // B..G
  const vals = faixa.getValues();
  const disp = faixa.getDisplayValues();
  const col = [[], [], [], [], []]; // série, tabela, desconto, negociado, família
  for (let r = 0; r < n; r++) {
    if (!(numPositivo_(vals[r][5]) > 0)) continue; // só maior que zero
    col[0].push(disp[r][0]); col[1].push(disp[r][2]); col[2].push(disp[r][3]);
    col[3].push(disp[r][4]); col[4].push(disp[r][5]);
  }
  if (col[0].length) {
    out.linhas.push(baseRow_(l, link)
      .concat(col.map(function (c) { return c.join(' | '); }))
      .concat([l[GERAL.COL_MARCA - 1]]));
  }
  return out;
}

function lerMaterial_(planilha, l, link) {
  const out = { linhas: [], logs: [] };
  const aba = achaAba_(planilha, MAT.ABA);
  if (!aba) { out.logs.push('PLANILHA INCONSISTENTE: aba "' + MAT.ABA + '" não encontrada'); return out; }
  const ren = lerSecaoMat_(aba, MAT.REN, 'Renovação (col. T)');
  const amp = lerSecaoMat_(aba, MAT.AMP, 'Ampliação (col. O)');
  ren.erros.concat(amp.erros).forEach(function (m) { out.logs.push('PLANILHA INCONSISTENTE: ' + m); });
  if (ren.itens.length || amp.itens.length) {
    out.linhas.push(baseRow_(l, link).concat([ren.itens.join(' | '), amp.itens.join(' | '), l[GERAL.COL_MARCA - 1]]));
  }
  return out;
}

function lerSecaoMat_(aba, cfg, rotulo) {
  const out = { itens: [], erros: [] };
  const cab = String(aba.getRange(cfg.cabLinha, cfg.col).getDisplayValue());
  if (norm_(cab).indexOf(MAT.CAB_ESPERADO) < 0) {
    out.erros.push(rotulo + ': cabeçalho esperado "Input final do contrato" não encontrado na linha ' +
      cfg.cabLinha + ' (encontrado: "' + cab.slice(0, 60) + '")');
    return out;
  }
  const n = cfg.fim - cfg.ini + 1;
  const vals = aba.getRange(cfg.ini, 1, n, cfg.col).getDisplayValues(); // A..coluna alvo
  const limpa = function (x) { x = String(x || '').trim(); return x.charAt(0) === '#' ? '' : x; };
  let comErro = 0;
  for (let r = 0; r < n; r++) {
    const v = String(vals[r][cfg.col - 1]).trim();
    if (v === '') continue;
    if (v.charAt(0) === '#') { comErro++; continue; }
    if (!(numPositivo_(v) > 0)) continue; // só maior que zero
    const marca = limpa(vals[r][1]);                                              // B
    const material = limpa(vals[r][4]) || limpa(vals[r][0]) || '(sem material)';  // E, senão A
    const serie = limpa(vals[r][3]);                                              // D
    out.itens.push((marca ? marca + ' - ' : '') + material + (serie ? ' (' + serie + ')' : '') + ': ' + v);
  }
  if (comErro) out.erros.push(rotulo + ': ' + comErro + ' célula(s) com erro (#REF! etc.)');
  return out;
}

/**
 * Potencializadores: uma linha por material com preço B2C > 0.
 * Colunas lidas em "Material opcional": B marca, D série, E material (senão A), preço na col. T/O.
 */
function lerPot_(planilha, l, link) {
  const out = { linhas: [], logs: [] };
  const aba = achaAba_(planilha, MAT.ABA);
  if (!aba) { out.logs.push('PLANILHA INCONSISTENTE: aba "' + MAT.ABA + '" não encontrada'); return out; }
  const cnpj = normCnpj_(l[GERAL.COL_CNPJ - 1]);
  const secoes = [[MAT.REN, 'Renovação']];
  if (POT.INCLUIR_AMPLIACAO) secoes.push([MAT.AMP, 'Ampliação']);
  secoes.forEach(function (s) {
    const cfg = s[0], origem = s[1];
    const cab = String(aba.getRange(cfg.cabLinha, cfg.col).getDisplayValue());
    const ok = POT.CABS_ACEITOS.some(function (t) { return norm_(cab).indexOf(t) >= 0; });
    if (!ok) {
      out.logs.push('PLANILHA INCONSISTENTE: ' + origem + ': cabeçalho de preço não encontrado na linha ' +
        cfg.cabLinha + ' (encontrado: "' + cab.slice(0, 60) + '")');
      return;
    }
    const n = cfg.fim - cfg.ini + 1;
    const colMax = Math.max(cfg.col, POT.COL_ID_MATERIAL);
    const vals = aba.getRange(cfg.ini, 1, n, colMax).getDisplayValues();
    const limpa = function (x) { x = String(x || '').trim(); return x.charAt(0) === '#' ? '' : x; };
    let comErro = 0;
    for (let r = 0; r < n; r++) {
      const v = String(vals[r][cfg.col - 1]).trim();
      if (v === '') continue;
      if (v.charAt(0) === '#') { comErro++; continue; }
      const preco = numPositivo_(v);
      if (!(preco > 0)) continue;
      const material = limpa(vals[r][4]) || limpa(vals[r][0]) || '(sem material)';
      const idMat = POT.COL_ID_MATERIAL ? limpa(vals[r][POT.COL_ID_MATERIAL - 1]) : '';
      out.linhas.push([link, cnpj, l[GERAL.COL_LINK_PIC - 1], l[GERAL.COL_VERSAO_PIC - 1], l[GERAL.COL_MARCA - 1], l[GERAL.COL_FRENTE - 1], origem,
        limpa(vals[r][3]), idMat, material, preco, l[GERAL.COL_CONSULTOR - 1]]);
    }
    if (comErro) out.logs.push('PLANILHA INCONSISTENTE: ' + origem + ': ' + comErro + ' célula(s) com erro (#REF! etc.)');
  });
  return out;
}

function lerB2C_(planilha, l, link) {
  const out = { linhas: [], logs: [] };
  const sim = planilha.getSheetByName(B2C.ABA);
  if (!sim) { out.logs.push('PLANILHA INCONSISTENTE: aba "' + B2C.ABA + '" não encontrada'); return out; }
  const b = B2C.CAB;
  const cabs = sim.getRange(b.ini, B2C.COL, b.fim - b.ini + 1, 1).getDisplayValues();
  if (!cabs.some(function (r) { return norm_(r[0]).indexOf(b.texto) >= 0; })) {
    out.logs.push('PLANILHA INCONSISTENTE: cabeçalho "Preço de venda B2C" não encontrado na coluna W (linhas ' + b.ini + '-' + b.fim + ')');
    return out;
  }
  const n = B2C.FIM - B2C.INI + 1;
  const faixa = sim.getRange(B2C.INI, 1, n, B2C.COL); // A..W
  const vals = faixa.getValues();
  const disp = faixa.getDisplayValues();
  const col = [[], [], [], []]; // segmento (B), série (C), material col. 27 (L), preço (W)
  let comErro = 0;
  for (let r = 0; r < n; r++) {
    const bruto = vals[r][B2C.COL - 1];
    if (bruto === '' || bruto === null) continue;
    if (String(bruto).charAt(0) === '#') { comErro++; continue; }
    if (!(numPositivo_(bruto) > 0)) continue; // só maior que zero
    col[0].push(disp[r][1]); col[1].push(disp[r][2]); col[2].push(disp[r][11]); col[3].push(disp[r][B2C.COL - 1]);
  }
  if (comErro) out.logs.push('PLANILHA INCONSISTENTE: ' + comErro + ' célula(s) com erro (#REF! etc.) na coluna W');
  if (col[3].length) {
    out.linhas.push(baseRow_(l, link).concat([l[GERAL.COL_MARCA - 1]])
      .concat(col.map(function (c) { return c.join(' | '); })));
  }
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
/** Chave de "repetido": a do job (ex.: CNPJ + marca) ou, por padrão, o próprio link. */
function chaveDe_(job, l, link) {
  return job.chaveDedupe ? job.chaveDedupe(l) : link;
}
/** Para cada chave, o índice do pedido mais recente (empate: o que está mais abaixo na aba). */
function escolherVencedores_(aba, dados, rich, cnpjs, job) {
  const grupos = new Map();
  dados.forEach(function (l, i) {
    if (!dentroDoPeriodo_(l[GERAL.COL_ABERTURA - 1])) return;
    if (GERAL.FILTRAR_CNPJ && !cnpjs.has(normCnpj_(l[GERAL.COL_CNPJ - 1]))) return;
    const link = extrairLink_(l[GERAL.COL_LINK - 1], rich[i][0]);
    if (!link) return;
    const chave = chaveDe_(job, l, link);
    if (!grupos.has(chave)) grupos.set(chave, []);
    grupos.get(chave).push(i);
  });
  const vencedor = new Map();
  grupos.forEach(function (idx, chave) {
    let cand = idx;
    if (idx.length > 1) { // só confere filtro nos repetidos
      cand = idx.filter(function (i) { return !(aba.isRowHiddenByFilter(i + 2) || aba.isRowHiddenByUser(i + 2)); });
    }
    if (!cand.length) return;
    let melhor = cand[0], tm = tempoPedido_(dados[melhor][GERAL.COL_ABERTURA - 1]);
    cand.forEach(function (i) {
      const t = tempoPedido_(dados[i][GERAL.COL_ABERTURA - 1]);
      if (t >= tm) { melhor = i; tm = t; }
    });
    vencedor.set(chave, melhor);
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
