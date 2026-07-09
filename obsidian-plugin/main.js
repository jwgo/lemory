"use strict";
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

// main.ts
var main_exports = {};
__export(main_exports, {
  default: () => LemoryPlugin
});
module.exports = __toCommonJS(main_exports);
var import_obsidian = require("obsidian");
var DEFAULT_SETTINGS = { serverUrl: "http://127.0.0.1:8377" };
var VIEW_TYPE = "lemory-view";
var LemoryPlugin = class extends import_obsidian.Plugin {
  constructor() {
    super(...arguments);
    this.settings = DEFAULT_SETTINGS;
  }
  async onload() {
    await this.loadSettings();
    this.registerView(VIEW_TYPE, (leaf) => new LemoryView(leaf, this));
    this.addRibbonIcon("brain-circuit", "Lemory: ask your vault", () => this.activateView());
    this.addCommand({
      id: "open-lemory",
      name: "Ask your vault (open panel)",
      callback: () => this.activateView()
    });
    this.addCommand({
      id: "lemory-search-selection",
      name: "Search vault for selected text",
      editorCallback: async (editor) => {
        const q = editor.getSelection().trim();
        if (!q) return new import_obsidian.Notice("Select some text first");
        const view = await this.activateView();
        view?.runSearch(q);
      }
    });
    this.addSettingTab(new LemorySettingTab(this.app, this));
  }
  onunload() {
  }
  async activateView() {
    const existing = this.app.workspace.getLeavesOfType(VIEW_TYPE)[0];
    const leaf = existing ?? this.app.workspace.getRightLeaf(false);
    if (!leaf) return null;
    await leaf.setViewState({ type: VIEW_TYPE, active: true });
    this.app.workspace.revealLeaf(leaf);
    return leaf.view instanceof LemoryView ? leaf.view : null;
  }
  async api(path, init) {
    const url = `${this.settings.serverUrl.replace(/\/$/, "")}${path}`;
    let res;
    try {
      res = await fetch(url, init);
    } catch (e) {
      throw new Error(
        "Lemory \uC11C\uBC84\uC5D0 \uC5F0\uACB0\uD560 \uC218 \uC5C6\uC2B5\uB2C8\uB2E4. \uD130\uBBF8\uB110\uC5D0\uC11C `lemory serve` \uB97C \uC2E4\uD589\uD574 \uB450\uC138\uC694."
      );
    }
    if (!res.ok) throw new Error(`Lemory server error ${res.status}: ${await res.text()}`);
    return res.json();
  }
  async loadSettings() {
    this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
  }
  async saveSettings() {
    await this.saveData(this.settings);
  }
};
var LemoryView = class extends import_obsidian.ItemView {
  constructor(leaf, plugin) {
    super(leaf);
    this.plugin = plugin;
  }
  getViewType() {
    return VIEW_TYPE;
  }
  getDisplayText() {
    return "Lemory";
  }
  getIcon() {
    return "brain-circuit";
  }
  async onOpen() {
    const root = this.contentEl;
    root.empty();
    root.addClass("lemory-root");
    const form = root.createEl("div", { cls: "lemory-form" });
    this.input = form.createEl("input", {
      type: "text",
      placeholder: "\uC694\uC0C8 \uB0B4\uAC00 \uD558\uB358 \uADF8\uAC70 \uBB50\uC600\uC9C0?"
    });
    this.input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") this.runAsk(this.input.value.trim());
    });
    const askBtn = form.createEl("button", { text: "\uC9C8\uBB38" });
    askBtn.addEventListener("click", () => this.runAsk(this.input.value.trim()));
    const searchBtn = form.createEl("button", { text: "\uAC80\uC0C9", cls: "lemory-secondary" });
    searchBtn.addEventListener("click", () => this.runSearch(this.input.value.trim()));
    this.output = root.createEl("div", { cls: "lemory-output" });
    this.output.createEl("div", {
      cls: "lemory-hint",
      text: "Enter = LLM \uB2F5\uBCC0(\uCD9C\uCC98 \uD3EC\uD568) \xB7 \uAC80\uC0C9 = \uAD00\uB828 \uB178\uD2B8 \uC989\uC2DC \uB098\uC5F4"
    });
  }
  busy(msg) {
    this.output.empty();
    this.output.createEl("div", { cls: "lemory-hint", text: msg });
  }
  fail(e) {
    this.output.empty();
    this.output.createEl("div", { cls: "lemory-error", text: String(e.message ?? e) });
  }
  renderHits(hits) {
    const list = this.output.createEl("div");
    for (const h of hits) {
      const item = list.createEl("div", { cls: "lemory-hit" });
      const link = item.createEl("a", {
        text: h.title + (h.heading ? ` \u203A ${h.heading}` : ""),
        cls: "lemory-hit-title"
      });
      link.addEventListener("click", () => {
        this.app.workspace.openLinkText(h.path, "", false);
      });
      if (h.date) item.createEl("span", { cls: "lemory-date", text: ` ${h.date}` });
      if (h.text) item.createEl("div", { cls: "lemory-excerpt", text: h.text.slice(0, 200) });
    }
  }
  async runSearch(q) {
    if (!q) return;
    this.input.value = q;
    this.busy("\uAC80\uC0C9 \uC911\u2026");
    try {
      const hits = await this.plugin.api(`/search?q=${encodeURIComponent(q)}&k=8`);
      this.output.empty();
      this.renderHits(hits);
    } catch (e) {
      this.fail(e);
    }
  }
  async runAsk(q) {
    if (!q) return;
    this.busy("\uC0DD\uAC01 \uC911\u2026 (LLM \uD638\uCD9C)");
    try {
      const res = await this.plugin.api("/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q, k: 8 })
      });
      this.output.empty();
      this.output.createEl("div", { cls: "lemory-answer", text: res.answer });
      this.output.createEl("div", { cls: "lemory-hint", text: "\uCD9C\uCC98" });
      this.renderHits(res.sources ?? []);
    } catch (e) {
      this.fail(e);
    }
  }
  async onClose() {
  }
};
var LemorySettingTab = class extends import_obsidian.PluginSettingTab {
  constructor(app, plugin) {
    super(app, plugin);
    this.plugin = plugin;
  }
  display() {
    const { containerEl } = this;
    containerEl.empty();
    new import_obsidian.Setting(containerEl).setName("Server URL").setDesc("Address of your local `lemory serve` backend").addText(
      (t) => t.setValue(this.plugin.settings.serverUrl).onChange(async (v) => {
        this.plugin.settings.serverUrl = v.trim() || DEFAULT_SETTINGS.serverUrl;
        await this.plugin.saveSettings();
      })
    );
  }
};
