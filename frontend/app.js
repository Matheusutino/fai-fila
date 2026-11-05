const $ = (id) => document.getElementById(id);
let selectedFile = null,
  objectUrl = null,
  submissionKey = null,
  run = 0;
const referenceFiles = new Map();
let uploadedDocument = null;
const stateLabels = {
  pending: "Solicitação recebida",
  queued: "Na fila",
  processing: "Análise em andamento",
  retrying: "Aguardando nova tentativa",
  succeeded: "Análise concluída",
  failed: "Não foi possível concluir",
};
const stageLabels = {
  extracting: "Extraindo o texto e os campos do recibo.",
  structuring: "Identificando valor, data, estabelecimento e identificador.",
  retrieving: "Procurando recibos semelhantes na base.",
  comparing: "Comparando os campos dos recibos.",
  indexing: "Registrando o recibo aprovado na base.",
};
const decisions = {
  possible_duplicate: "Possível duplicidade",
  no_duplicate_found: "Nenhuma duplicidade encontrada",
  inconclusive: "Análise inconclusiva",
  distinct: "Campos diferentes",
};
const fieldNames = {
  amount: "Valor",
  transaction_date: "Data da transação",
  merchant: "Estabelecimento",
  receipt_identifier: "Identificador",
};
function node(tag, text, cls) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (cls) el.className = cls;
  return el;
}
function viewDocument(url, filename, mime) {
  $("document-title").textContent = filename;
  $("open-document").href = url;
  const preview = node(mime.startsWith("image/") ? "img" : "iframe");
  preview.src = url;
  if (preview.tagName === "IMG") preview.alt = filename;
  else preview.title = "Visualização de " + filename;
  $("document-content").replaceChildren(preview);
  $("document-viewer").showModal();
}
$("close-document").addEventListener("click", () => $("document-viewer").close());
$("document-viewer").addEventListener("close", () => $("document-content").replaceChildren());
$("view-selected").addEventListener("click", () => {
  if (selectedFile && objectUrl)
    viewDocument(objectUrl, selectedFile.name, selectedFile.type);
});
$("view-uploaded").addEventListener("click", () => {
  if (uploadedDocument)
    viewDocument(uploadedDocument.url, uploadedDocument.filename, uploadedDocument.mime);
});
async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok)
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : "Não foi possível completar a solicitação.",
    );
  return body;
}
function selectFile(file) {
  selectedFile = file;
  submissionKey = crypto.randomUUID();
  $("submit").disabled = !file;
  $("upload-error").textContent = "";
  if (objectUrl) URL.revokeObjectURL(objectUrl);
  $("selected").hidden = !file;
  $("preview").hidden = true;
  $("view-selected").hidden = !file;
  objectUrl = null;
  if (!file) return;
  $("filename").textContent = file.name;
  objectUrl = URL.createObjectURL(file);
  if (file.type.startsWith("image/")) {
    $("preview").src = objectUrl;
    $("preview").hidden = false;
  }
}
$("file").addEventListener("change", (event) =>
  selectFile(event.target.files[0]),
);
for (const type of ["dragover", "dragleave", "drop"])
  $("dropzone").addEventListener(type, (event) => {
    event.preventDefault();
    $("dropzone").classList.toggle("drag", type === "dragover");
    if (type === "drop") selectFile(event.dataTransfer.files[0]);
  });
$("upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!selectedFile) return;
  $("submit").disabled = true;
  $("upload-error").textContent = "";
  const form = new FormData();
  form.append("file", selectedFile);
  try {
    const job = await api("/api/receipt-checks", {
      method: "POST",
      body: form,
      headers: { "Idempotency-Key": submissionKey },
    });
    follow(job.token);
  } catch (error) {
    $("upload-error").textContent = error.message;
  } finally {
    $("submit").disabled = !selectedFile;
  }
});
function update(job) {
  uploadedDocument = {
    url: "/api/receipt-checks/" + encodeURIComponent(job.token) + "/file",
    filename: job.filename,
    mime: job.mime,
  };
  $("empty").hidden = true;
  $("tracking").hidden = false;
  $("task-status").textContent = stateLabels[job.status] || job.status;
  $("task-attempt").textContent = job.attempts
    ? `Tentativa ${job.attempts}`
    : "";
  $("current-token").textContent = job.token;
  $("token-input").value = job.token;
  const step =
    job.status === "succeeded"
      ? 5
      : { extracting: 2, structuring: 2, retrieving: 3, comparing: 4 }[job.stage] || 1;
  [...$("timeline").children].forEach((el, i) =>
    el.classList.toggle("done", i < step),
  );
  $("task-message").textContent =
    job.error?.message ||
    stageLabels[job.stage] ||
    (job.status === "succeeded"
      ? "Confira os campos e as evidências abaixo."
      : "Você pode sair desta página e retomar com o token.");
  if (job.status === "succeeded" && job.result?.decision)
    renderResult(job.result);
}
async function follow(token) {
  const current = ++run;
  let failures = 0;
  $("result").hidden = true;
  $("upload-error").textContent = "";
  while (current === run) {
    try {
      const job = await api("/api/receipt-checks/" + encodeURIComponent(token));
      if (current !== run) return;
      update(job);
      failures = 0;
      if (["succeeded", "failed"].includes(job.status)) return;
    } catch (error) {
      if (current !== run) return;
      failures++;
      $("upload-error").textContent =
        error.message +
        (failures < 5
          ? " Tentando consultar novamente…"
          : " Use o token para retomar a consulta.");
      if (failures >= 5) return;
    }
    await new Promise((resolve) =>
      setTimeout(resolve, Math.min(15000, 2000 * 2 ** failures)),
    );
  }
}
function value(receipt, field) {
  if (field === "amount") {
    if (receipt.amount_minor == null || !receipt.currency)
      return "Não identificado";
    try {
      return new Intl.NumberFormat("pt-BR", {
        style: "currency",
        currency: receipt.currency,
      }).format(receipt.amount_minor / 100);
    } catch {
      return `${receipt.amount_minor / 100} ${receipt.currency}`;
    }
  }
  if (field === "merchant")
    return (
      [receipt.merchant_name, receipt.merchant_tax_id]
        .filter(Boolean)
        .join(" · ") || "Não identificado"
    );
  return receipt[field] || "Não identificado";
}
function renderResult(result) {
  const host = $("result");
  host.replaceChildren();
  host.hidden = false;
  const heading = node("div", undefined, "result-heading");
  heading.append(
    node("h2", "Resultado da conferência"),
    node(
      "span",
      decisions[result.decision],
      "badge" + (result.decision === "no_duplicate_found" ? " clear" : ""),
    ),
  );
  host.append(heading);
  host.append(node("p", result.limitation));
  const fields = node("div", undefined, "receipt-fields");
  for (const [field, label] of Object.entries(fieldNames)) {
    const item = node("div");
    item.append(
      node("div", label, "field-label"),
      node("div", value(result.receipt, field), "field-value"),
    );
    fields.append(item);
  }
  host.append(fields);
  if (result.receipt.ambiguities?.length)
    host.append(
      node(
        "p",
        "Pontos para revisão: " + result.receipt.ambiguities.join("; "),
        "error",
      ),
    );
  host.append(
    node(
      "p",
      `${result.matches.length} candidato(s) recuperado(s) · Política ${result.rule_version}`,
    ),
  );
  for (const match of result.matches) {
    const card = node("article", undefined, "candidate"),
      head = node("div", undefined, "candidate-head");
    head.append(
      node("h3", match.receipt_id),
      node(
        "span",
        decisions[match.decision] || match.decision,
        "badge" + (match.decision === "distinct" ? " clear" : ""),
      ),
    );
    card.append(head, node("p", match.reason));
    const original = referenceFiles.get(match.receipt_id);
    if (original && original.sha256 === match.file_hash) {
      const button = node("button", "Visualizar PDF original", "text-button");
      button.type = "button";
      button.addEventListener("click", () =>
        viewDocument(original.url, original.filename, "application/pdf"),
      );
      card.append(button);
    }
    const table = node("table"),
      row = node("tr");
    for (const title of [
      "Campo",
      "Recibo enviado",
      "Recibo da base",
      "Comparação",
    ])
      row.append(node("th", title));
    const thead = node("thead");
    thead.append(row);
    table.append(thead);
    const tbody = node("tbody");
    for (const [field, label] of Object.entries(fieldNames)) {
      const tr = node("tr");
      const status = match.matched_fields.includes(field)
        ? "Coincide"
        : match.conflicting_fields.includes(field)
          ? "Diverge"
          : "Dados insuficientes";
      tr.append(
        node("td", label),
        node("td", value(result.receipt, field)),
        node("td", value(match.receipt, field)),
        node(
          "td",
          status,
          status === "Coincide"
            ? "match"
            : status === "Diverge"
              ? "conflict"
              : "",
        ),
      );
      tbody.append(tr);
    }
    table.append(tbody);
    const wrap = node("div", undefined, "table-wrap");
    wrap.append(table);
    card.append(wrap);
    const detail = node("details");
    detail.append(
      node("summary", "Ver texto do recibo da base"),
      node("pre", match.text),
    );
    card.append(detail);
    host.append(card);
  }
  const detail = node("details");
  detail.append(
    node("summary", "Ver texto extraído do recibo enviado"),
    node("pre", result.text),
  );
  host.append(detail);
}
$("resume").addEventListener("click", () => {
  const token = $("token-input").value.trim();
  if (token) follow(token);
});
$("copy-token").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("current-token").textContent);
    $("copy-token").textContent = "Copiado";
  } catch {
    $("copy-token").textContent = "Selecione e copie o token acima";
  }
});
$("use-example").addEventListener("click", async () => {
  const filename = $("example").value;
  if (!filename) return;
  try {
    const response = await fetch(
      "/api/examples/" + encodeURIComponent(filename),
    );
    if (!response.ok) throw new Error("Exemplo indisponível.");
    const blob = await response.blob();
    selectFile(new File([blob], filename, { type: blob.type }));
  } catch (error) {
    $("upload-error").textContent = error.message;
  }
});
async function loadExamples() {
  try {
    const items = await api("/api/examples");
    $("example").replaceChildren();
    if (!items.length) {
      $("example").append(node("option", "Nenhum exemplo gerado"));
      $("use-example").disabled = true;
    }
    for (const item of items) {
      const option = node("option", item.label);
      option.value = item.filename;
      $("example").append(option);
    }
  } catch {
    $("example").replaceChildren(node("option", "Exemplos indisponíveis"));
  }
}
async function loadReferences() {
  const host = $("reference-list");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  host.textContent = "Carregando originais…";
  try {
    const items = await api("/api/reference-receipts", {
      signal: controller.signal,
      cache: "no-store",
    });
    host.replaceChildren();
    for (const item of items) {
      referenceFiles.set(item.receipt_id, item);
      const button = node("button", `${item.label} · ${item.filename}`, "text-button");
      button.type = "button";
      button.addEventListener("click", () =>
        viewDocument(item.url, item.filename, "application/pdf"),
      );
      host.append(button);
    }
    if (!items.length) host.textContent = "Nenhum original disponível.";
  } catch {
    host.textContent = "Não foi possível carregar os originais.";
    const retry = node("button", "Tentar novamente", "text-button");
    retry.type = "button";
    retry.addEventListener("click", loadReferences);
    host.append(retry);
  } finally {
    clearTimeout(timeout);
  }
}
async function health() {
  try {
    const response = await fetch("/health/ready");
    const data = await response.json();
    $("connection").textContent =
      data.status === "ok"
        ? "Fila e processamento disponíveis"
        : "Processamento indisponível";
    $("connection").classList.toggle("degraded", data.status !== "ok");
  } catch {
    $("connection").textContent = "Sem conexão";
    $("connection").classList.add("degraded");
  }
}
$("upload-form").reset();
$("token-input").value = "";
loadExamples();
health();
setInterval(health, 10000);
loadReferences();
