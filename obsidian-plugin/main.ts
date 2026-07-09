import {
  App, ItemView, Notice, Plugin, PluginSettingTab, Setting, WorkspaceLeaf,
} from "obsidian";

interface LemorySettings {
  serverUrl: string;
}

const DEFAULT_SETTINGS: LemorySettings = { serverUrl: "http://127.0.0.1:8377" };
const VIEW_TYPE = "lemory-view";

interface Hit {
  path: string;
  title: string;
  heading: string;
  text?: string;
  date?: string | null;
  score: number;
}

export default class LemoryPlugin extends Plugin {
  settings: LemorySettings = DEFAULT_SETTINGS;

  async onload() {
    await this.loadSettings();
    this.registerView(VIEW_TYPE, (leaf) => new LemoryView(leaf, this));
    this.addRibbonIcon("brain-circuit", "Lemory: ask your vault", () => this.activateView());
    this.addCommand({
      id: "open-lemory",
      name: "Ask your vault (open panel)",
      callback: () => this.activateView(),
    });
    this.addCommand({
      id: "lemory-search-selection",
      name: "Search vault for selected text",
      editorCallback: async (editor) => {
        const q = editor.getSelection().trim();
        if (!q) return new Notice("Select some text first");
        const view = await this.activateView();
        view?.runSearch(q);
      },
    });
    this.addSettingTab(new LemorySettingTab(this.app, this));
  }

  onunload() {}

  async activateView(): Promise<LemoryView | null> {
    const existing = this.app.workspace.getLeavesOfType(VIEW_TYPE)[0];
    const leaf = existing ?? this.app.workspace.getRightLeaf(false);
    if (!leaf) return null;
    await leaf.setViewState({ type: VIEW_TYPE, active: true });
    this.app.workspace.revealLeaf(leaf);
    return leaf.view instanceof LemoryView ? leaf.view : null;
  }

  async api(path: string, init?: RequestInit): Promise<any> {
    const url = `${this.settings.serverUrl.replace(/\/$/, "")}${path}`;
    let res: Response;
    try {
      res = await fetch(url, init);
    } catch (e) {
      throw new Error(
        "Lemory 서버에 연결할 수 없습니다. 터미널에서 `lemory serve` 를 실행해 두세요.",
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
}

class LemoryView extends ItemView {
  plugin: LemoryPlugin;
  input!: HTMLInputElement;
  output!: HTMLElement;

  constructor(leaf: WorkspaceLeaf, plugin: LemoryPlugin) {
    super(leaf);
    this.plugin = plugin;
  }

  getViewType() { return VIEW_TYPE; }
  getDisplayText() { return "Lemory"; }
  getIcon() { return "brain-circuit"; }

  async onOpen() {
    const root = this.contentEl;
    root.empty();
    root.addClass("lemory-root");

    const form = root.createEl("div", { cls: "lemory-form" });
    this.input = form.createEl("input", {
      type: "text",
      placeholder: "요새 내가 하던 그거 뭐였지?",
    });
    this.input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") this.runAsk(this.input.value.trim());
    });
    const askBtn = form.createEl("button", { text: "질문" });
    askBtn.addEventListener("click", () => this.runAsk(this.input.value.trim()));
    const searchBtn = form.createEl("button", { text: "검색", cls: "lemory-secondary" });
    searchBtn.addEventListener("click", () => this.runSearch(this.input.value.trim()));

    this.output = root.createEl("div", { cls: "lemory-output" });
    this.output.createEl("div", {
      cls: "lemory-hint",
      text: "Enter = LLM 답변(출처 포함) · 검색 = 관련 노트 즉시 나열",
    });
  }

  private busy(msg: string) {
    this.output.empty();
    this.output.createEl("div", { cls: "lemory-hint", text: msg });
  }

  private fail(e: unknown) {
    this.output.empty();
    this.output.createEl("div", { cls: "lemory-error", text: String((e as Error).message ?? e) });
  }

  private renderHits(hits: Hit[]) {
    const list = this.output.createEl("div");
    for (const h of hits) {
      const item = list.createEl("div", { cls: "lemory-hit" });
      const link = item.createEl("a", {
        text: h.title + (h.heading ? ` › ${h.heading}` : ""),
        cls: "lemory-hit-title",
      });
      link.addEventListener("click", () => {
        this.app.workspace.openLinkText(h.path, "", false);
      });
      if (h.date) item.createEl("span", { cls: "lemory-date", text: ` ${h.date}` });
      if (h.text) item.createEl("div", { cls: "lemory-excerpt", text: h.text.slice(0, 200) });
    }
  }

  async runSearch(q: string) {
    if (!q) return;
    this.input.value = q;
    this.busy("검색 중…");
    try {
      const hits: Hit[] = await this.plugin.api(`/search?q=${encodeURIComponent(q)}&k=8`);
      this.output.empty();
      this.renderHits(hits);
    } catch (e) { this.fail(e); }
  }

  async runAsk(q: string) {
    if (!q) return;
    this.busy("생각 중… (LLM 호출)");
    try {
      const res = await this.plugin.api("/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q, k: 8 }),
      });
      this.output.empty();
      this.output.createEl("div", { cls: "lemory-answer", text: res.answer });
      this.output.createEl("div", { cls: "lemory-hint", text: "출처" });
      this.renderHits(res.sources ?? []);
    } catch (e) { this.fail(e); }
  }

  async onClose() {}
}

class LemorySettingTab extends PluginSettingTab {
  plugin: LemoryPlugin;

  constructor(app: App, plugin: LemoryPlugin) {
    super(app, plugin);
    this.plugin = plugin;
  }

  display(): void {
    const { containerEl } = this;
    containerEl.empty();
    new Setting(containerEl)
      .setName("Server URL")
      .setDesc("Address of your local `lemory serve` backend")
      .addText((t) =>
        t.setValue(this.plugin.settings.serverUrl).onChange(async (v) => {
          this.plugin.settings.serverUrl = v.trim() || DEFAULT_SETTINGS.serverUrl;
          await this.plugin.saveSettings();
        }),
      );
  }
}
