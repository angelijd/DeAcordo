/**
 * Extrai "Preço família" (aba Simulador, coluna G, linhas 38-57) dos simuladores
 * linkados na coluna AF da aba "Aprovacoes" (a partir de 01/09/2026).
 *
 * Saída:
 *  - CSV no Drive (pasta raiz) com uma linha por série que tenha Preço família
 *  - Aba "Log_Simulador" com links sem acesso / sem aba Simulador / erros
 *
 * Como usar: Extensões > Apps Script > cole este código > salve >
 * recarregue a planilha > menu "Simulador" > "Extrair preço família".
 * O processamento é retomado sozinho (gatilho) se passar do limite de 6 min.
 */

const CFG = {
  ABA_APROVACOES: 'Aprovacoes',
  ABA_SIMULADOR: 'Simulador',
  ABA_LOG: 'Log_Simulador',
  DATA_INICIO: new Date(2026, 8, 1),   // 01/09/2026
  COL_ABERTURA: 1,   // A
  COL_FRENTE: 2,     // B
  COL_CONSULTOR: 4,  // D (na amostra é "SOLICITANTE"; a coluna "CONSULTOR" fica mais à direita)
  COL_LINK: 32,      // AF
  LINHA_INI: 38,
  LINHA_FIM: 57,     // linha 58 é "Total" (sem preço família)
  // Simulador: B=série, D=preço tabela, E=desconto, F=negociado, G=preço família
  LIMITE_MS: 5 * 60 * 1000,
  NOME_CSV: 'preco_familia_simuladores.csv',
};

function onOpen() {
  SpreadsheetApp.getUi().createMenu('Simulador')
    .addItem('Extrair preço família', 'iniciar')
    .addToUi();
}

function iniciar() {
  const props = PropertiesService.getScriptProperties();
  props.deleteAllProperties();
  apagarGatilhos_();
  props.setProperty('estado', JSON.stringify({ proxima: 0, linhas: [], log: [] }));
  processar();
}

function processar() {
  const t0 = Date.now();
  const props = PropertiesService.getScriptProperties();
  const estado = JSON.parse(props.getProperty('estado'));
  const ss = SpreadsheetApp.getActive();
  const aba = ss.getSheetByName(CFG.ABA_APROVACOES);
  const ultima = aba.getLastRow();
  if (ultima < 2) return finalizar_(estado);

  const dados = aba.getRange(2, 1, ultima - 1, CFG.COL_LINK).getValues();
  const rich = aba.getRange(2, CFG.COL_LINK, ultima - 1, 1).getRichTextValues();

  const vistos = new Set(estado.vistos || []);
  let i = estado.proxima;
  for (; i < dados.length; i++) {
    if (Date.now() - t0 > CFG.LIMITE_MS) break;
    const l = dados[i];
    if (!(dentroDoPeriodo_(l[CFG.COL_ABERTURA - 1]))) continue;

    const link = extrairLink_(l[CFG.COL_LINK - 1], rich[i][0]);
    if (!link) continue;
    const id = idDoLink_(link);
    const linhaPlan = i + 2;
    if (!id) { estado.log.push([linhaPlan, link, 'Link inválido']); continue; }
    if (vistos.has(id)) continue;
    vistos.add(id);

    const frente = l[CFG.COL_FRENTE - 1];
    const consultor = l[CFG.COL_CONSULTOR - 1];
    let planilha;
    try {
      planilha = SpreadsheetApp.openById(id);
    } catch (e) {
      estado.log.push([linhaPlan, link, 'SEM ACESSO']);
      continue;
    }
    const sim = planilha.getSheetByName(CFG.ABA_SIMULADOR);
    if (!sim) { estado.log.push([linhaPlan, link, 'Aba "Simulador" não encontrada']); continue; }

    try {
      const n = CFG.LINHA_FIM - CFG.LINHA_INI + 1;
      const faixa = sim.getRange(CFG.LINHA_INI, 2, n, 6); // B..G
      const vals = faixa.getValues();
      const disp = faixa.getDisplayValues();
      for (let r = 0; r < n; r++) {
        const g = vals[r][5];
        if (g === '' || g === null) continue;
        estado.linhas.push([link, consultor, frente, disp[r][0],
          disp[r][2], disp[r][3], disp[r][4], disp[r][5]]);
      }
    } catch (e) {
      estado.log.push([linhaPlan, link, 'Erro: ' + e.message]);
    }
  }

  estado.proxima = i;
  estado.vistos = Array.from(vistos);
  if (i < dados.length) {
    props.setProperty('estado', JSON.stringify(estado));
    apagarGatilhos_();
    ScriptApp.newTrigger('processar').timeBased().after(60 * 1000).create();
    ss.toast('Continua em 1 min (linha ' + (i + 2) + ' de ' + (dados.length + 1) + ')');
    return;
  }
  finalizar_(estado);
}

function finalizar_(estado) {
  apagarGatilhos_();
  const cab = ['Link do simulador', 'Consultor', 'Frente', 'Série',
    'Preço de tabela', 'Desconto', 'Preço negociado', 'Preço família'];
  const csv = [cab].concat(estado.linhas).map(function (r) {
    return r.map(function (c) { return '"' + String(c).replace(/"/g, '""') + '"'; }).join(',');
  }).join('\n');
  const arq = DriveApp.createFile(CFG.NOME_CSV.replace('.csv', '_' + Utilities.formatDate(new Date(), 'America/Sao_Paulo', 'yyyyMMdd_HHmm') + '.csv'), '﻿' + csv, MimeType.CSV);

  const ss = SpreadsheetApp.getActive();
  let log = ss.getSheetByName(CFG.ABA_LOG) || ss.insertSheet(CFG.ABA_LOG);
  log.clear();
  log.getRange(1, 1, 1, 3).setValues([['Linha (Aprovacoes)', 'Link', 'Problema']]);
  if (estado.log.length) log.getRange(2, 1, estado.log.length, 3).setValues(estado.log);

  const semAcesso = estado.log.filter(function (x) { return x[2] === 'SEM ACESSO'; }).length;
  PropertiesService.getScriptProperties().deleteAllProperties();
  SpreadsheetApp.getUi().alert(
    'Concluído.\n' + estado.linhas.length + ' linhas no CSV: ' + arq.getUrl() +
    '\n\nLinks sem acesso: ' + semAcesso + ' (detalhes na aba "' + CFG.ABA_LOG + '")' +
    '\nOutros problemas: ' + (estado.log.length - semAcesso));
}

function dentroDoPeriodo_(v) {
  let d = v;
  if (!(d instanceof Date)) {
    const m = String(v).match(/(\d{1,2})\/(\d{1,2})\/(\d{4})/);
    if (!m) return false;
    d = new Date(+m[3], +m[2] - 1, +m[1]);
  }
  return d >= CFG.DATA_INICIO;
}

function extrairLink_(valor, rich) {
  const s = String(valor || '').trim();
  const m = s.match(/https?:\/\/\S+/);
  if (m) return m[0];
  return (rich && rich.getLinkUrl()) || '';
}

function idDoLink_(url) {
  const m = url.match(/\/d\/([a-zA-Z0-9_-]+)/) || url.match(/[?&]id=([a-zA-Z0-9_-]+)/);
  return m ? m[1] : null;
}

function apagarGatilhos_() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'processar') ScriptApp.deleteTrigger(t);
  });
}
