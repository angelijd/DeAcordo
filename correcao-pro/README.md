# Correção Pro (extensão do Chrome)

Guarda todas as suas cópias de texto e permite criar atalhos: digite `ponto` e ele vira o texto salvo.

## Instalar
1. Abra `chrome://extensions`
2. Ative o **Modo do desenvolvedor** (canto superior direito)
3. Clique em **Carregar sem compactação** e selecione esta pasta `correcao-pro`
4. Fixe o ícone azul na barra do Chrome

## Usar
- **Cópias**: todo Ctrl+C / Ctrl+X em páginas é salvo (até 500, sem duplicadas). Também dá para clicar com o botão direito numa seleção → *Correção Pro: salvar seleção*.
- **Criar atalho**: na aba *Cópias* clique em **Criar atalho** numa cópia, ou crie manualmente na aba *Atalhos*.
- **Expandir**: em qualquer campo de texto, digite o atalho + espaço (ou imediatamente, se escolher isso em *Config*).
- **Backup**: exporte/importe tudo em JSON na aba *Config*.

Os dados ficam só no seu navegador (`chrome.storage.local`).
Obs.: o Chrome não deixa extensões rodarem em `chrome://`, na Chrome Web Store, e alguns editores (ex.: Google Docs) usam campos próprios onde a expansão pode não funcionar.
