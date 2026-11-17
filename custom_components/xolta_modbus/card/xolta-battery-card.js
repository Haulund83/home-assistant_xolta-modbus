/*
 * Xolta battery card - shipped and registered by the xolta_modbus integration.
 *
 * Plain web component: no build step and no third-party libraries, so it does not
 * break when libraries change. It finds the integration's entities by their
 * translation key, so it works in every language without configuration.
 */
const CARD = "xolta-battery-card";
const VERSION = "0.2.1";
const PLATFORM = "xolta_modbus";

const TEXT = {
  en: {
    name: "Battery",
    soc: "State of charge",
    grid: "Grid",
    solar: "Solar",
    home: "Home",
    override: "Override",
    auto: "Auto",
    stop: "Stop",
    self_consumption: "Self-consumption",
    ends: "Ends",
    contested: "The battery is not following the override",
    missing: "No Ebbefos / Xolta battery found. Add the integration first.",
    unavailable: "No connection to the battery",
    description: "State of charge, charging status and override for an Ebbefos / Xolta battery (local Modbus).",
  },
  da: {
    name: "Batteri",
    soc: "Ladetilstand",
    grid: "Net",
    solar: "Sol",
    home: "Hus",
    override: "Overstyring",
    auto: "Auto",
    stop: "Stop",
    self_consumption: "Eget forbrug",
    ends: "Slutter",
    contested: "Batteriet følger ikke overstyringen",
    missing: "Intet Ebbefos / Xolta-batteri fundet. Tilføj integrationen først.",
    unavailable: "Ingen forbindelse til batteriet",
    description: "Ladetilstand, ladestatus og overstyring for et Ebbefos / Xolta-batteri (lokal Modbus).",
  },
};

const KEYS = {
  soc: "state_of_charge",
  power: "power",
  activity: "activity",
  state: "state",
  override: "override",
  ends: "override_ends",
  contested: "override_contested",
};

const ICONS = {
  charging: "mdi:arrow-up-bold",
  discharging: "mdi:arrow-down-bold",
  standby: "mdi:pause",
};

function text(hass) {
  const lang = (hass && (hass.locale?.language || hass.language)) || "en";
  return TEXT[lang.split("-")[0]] || TEXT.en;
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

/** Find this integration's entities, optionally limited to one device. */
function findEntities(hass, deviceId) {
  const found = {};
  for (const entry of Object.values(hass.entities || {})) {
    if (entry.platform !== PLATFORM) continue;
    if (deviceId && entry.device_id !== deviceId) continue;
    for (const [name, key] of Object.entries(KEYS)) {
      if (entry.translation_key === key && !found[name]) found[name] = entry.entity_id;
    }
  }
  return found;
}

class XoltaBatteryCard extends HTMLElement {
  static getStubConfig() {
    return {};
  }

  static getConfigForm() {
    return {
      schema: [
        { name: "name", selector: { text: {} } },
        { name: "device_id", selector: { device: { integration: PLATFORM } } },
        {
          type: "grid",
          name: "",
          schema: [
            { name: "grid_power", selector: { entity: { domain: "sensor", device_class: "power" } } },
            { name: "solar_power", selector: { entity: { domain: "sensor", device_class: "power" } } },
            { name: "home_power", selector: { entity: { domain: "sensor", device_class: "power" } } },
          ],
        },
        { name: "show_control", default: true, selector: { boolean: {} } },
      ],
      computeLabel: (schema) =>
        ({
          name: "Name",
          device_id: "Battery (only needed with more than one)",
          grid_power: "Grid power (optional)",
          solar_power: "Solar power (optional)",
          home_power: "Home power (optional)",
          show_control:
            "Show override (only when control is turned on in the integration: Settings → Devices & services → Xolta → Configure)",
        })[schema.name],
    };
  }

  setConfig(config) {
    this._config = { show_control: true, ...(config || {}) };
    this._lastKey = undefined;
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 4;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  _state(entityId) {
    return entityId ? this._hass.states[entityId] : undefined;
  }

  _format(stateObj) {
    if (!stateObj) return "";
    return this._hass.formatEntityState ? this._hass.formatEntityState(stateObj) : stateObj.state;
  }

  _moreInfo(entityId) {
    if (!entityId) return;
    this.dispatchEvent(
      new CustomEvent("hass-more-info", { detail: { entityId }, bubbles: true, composed: true })
    );
  }

  _render() {
    if (!this._config || !this._hass) return;
    const hass = this._hass;
    const t = text(hass);
    const ids = findEntities(hass, this._config.device_id);
    const extra = ["grid_power", "solar_power", "home_power"].map((k) => this._config[k]);
    const watched = [...Object.values(ids), ...extra].filter(Boolean);
    // The key includes the formatted text, so the card also redraws when Home Assistant
    // finishes loading its translations (the state itself does not change then).
    const key =
      watched
        .map((id) => `${id}=${hass.states[id]?.state}|${hass.states[id]?.last_updated}|${this._format(hass.states[id])}`)
        .join(",") + hass.language;
    if (key === this._lastKey) return; // nothing relevant changed
    this._lastKey = key;

    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const title = esc(this._config.name || t.name);

    if (!ids.soc) {
      this.shadowRoot.innerHTML = `${STYLE}<ha-card><div class="missing">${esc(t.missing)}</div></ha-card>`;
      return;
    }

    const soc = this._state(ids.soc);
    const socValue = Number(soc?.state);
    const available = soc && Number.isFinite(socValue);
    const pct = available ? Math.max(0, Math.min(100, socValue)) : 0;
    const level = pct < 15 ? "low" : pct < 30 ? "mid" : "ok";
    const activity = this._state(ids.activity);
    const act = activity?.state;
    const power = this._state(ids.power);
    const powerKw = Math.abs(Number(power?.state));
    const powerText = Number.isFinite(powerKw) && act !== "standby"
      ? `${powerKw.toLocaleString(hass.locale?.language || hass.language, { maximumFractionDigits: 2, minimumFractionDigits: 2 })} kW`
      : "";

    const flows = [
      ["grid", this._config.grid_power, "mdi:transmission-tower"],
      ["solar", this._config.solar_power, "mdi:solar-power"],
      ["home", this._config.home_power, "mdi:home-lightning-bolt"],
    ]
      .filter(([, id]) => id && this._state(id))
      .map(
        ([name, id, icon]) =>
          `<button class="flow" data-entity="${esc(id)}"><ha-icon icon="${icon}"></ha-icon><span class="label">${esc(t[name])}</span><span class="value">${esc(this._format(this._state(id)))}</span></button>`
      )
      .join("");

    let control = "";
    const override = this._state(ids.override);
    if (this._config.show_control && override) {
      const options = ["auto", "stop", "self_consumption"];
      const ends = this._state(ids.ends);
      const endsText =
        override.state !== "auto" && ends && !["unknown", "unavailable"].includes(ends.state)
          ? `${esc(t.ends)} ${esc(
              new Date(ends.state).toLocaleTimeString(hass.locale?.language || hass.language, {
                hour: "2-digit",
                minute: "2-digit",
              })
            )}`
          : "";
      const contested = this._state(ids.contested)?.state === "on";
      control = `
        <div class="control">
          <div class="row"><span class="label">${esc(t.override)}</span><span class="ends">${endsText}</span></div>
          <div class="segments" role="group">
            ${options
              .map(
                (o) =>
                  `<button class="segment ${override.state === o ? "active" : ""}" data-option="${o}" ${
                    override.state === "unavailable" ? "disabled" : ""
                  }>${esc(t[o])}</button>`
              )
              .join("")}
          </div>
          ${contested ? `<div class="warning"><ha-icon icon="mdi:alert"></ha-icon>${esc(t.contested)}</div>` : ""}
        </div>`;
    }

    this.shadowRoot.innerHTML = `${STYLE}
      <ha-card>
        <div class="header">${title}</div>
        <div class="main">
          <button class="battery ${level}" data-entity="${esc(ids.soc)}" aria-label="${esc(t.soc)}">
            <svg viewBox="0 0 60 100" aria-hidden="true">
              <rect x="20" y="2" width="20" height="8" rx="2" class="cap"></rect>
              <rect x="4" y="9" width="52" height="88" rx="9" class="shell"></rect>
              <rect x="10" y="${15 + (76 * (100 - pct)) / 100}" width="40" height="${(76 * pct) / 100}" rx="4" class="fill"></rect>
            </svg>
          </button>
          <div class="facts">
            <button class="soc" data-entity="${esc(ids.soc)}">${available ? `${Math.round(pct)}<span class="unit">%</span>` : "–"}</button>
            ${
              available
                ? `<button class="activity ${esc(act)}" data-entity="${esc(ids.activity || ids.power)}">
                    <ha-icon icon="${ICONS[act] || "mdi:battery"}"></ha-icon>
                    <span>${esc(this._format(activity))}</span>
                    ${powerText ? `<span class="power">${esc(powerText)}</span>` : ""}
                  </button>
                  <button class="state" data-entity="${esc(ids.state)}">${esc(this._format(this._state(ids.state)))}</button>`
                : `<div class="state">${esc(t.unavailable)}</div>`
            }
          </div>
        </div>
        ${flows ? `<div class="flows">${flows}</div>` : ""}
        ${control}
      </ha-card>`;

    this.shadowRoot.querySelectorAll("[data-entity]").forEach((el) =>
      el.addEventListener("click", () => this._moreInfo(el.dataset.entity))
    );
    this.shadowRoot.querySelectorAll("[data-option]").forEach((el) =>
      el.addEventListener("click", () =>
        hass.callService("select", "select_option", { entity_id: ids.override, option: el.dataset.option })
      )
    );
  }
}

const STYLE = `<style>
  ha-card { padding: 16px; }
  button { font: inherit; color: inherit; background: none; border: 0; padding: 0; cursor: pointer; text-align: left; }
  .header { font-size: 1.1rem; font-weight: 500; margin-bottom: 12px; color: var(--primary-text-color); }
  .main { display: flex; align-items: center; gap: 20px; }
  .battery { width: 64px; flex: none; }
  .battery svg { width: 64px; height: 106px; display: block; }
  .cap, .shell { fill: none; stroke: var(--secondary-text-color); stroke-width: 4; }
  .cap { fill: var(--secondary-text-color); stroke: none; }
  .fill { fill: var(--success-color, #43a047); transition: y .6s, height .6s; }
  .mid .fill { fill: var(--warning-color, #ffa600); }
  .low .fill { fill: var(--error-color, #db4437); }
  .facts { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .soc { font-size: 2.6rem; font-weight: 400; line-height: 1; color: var(--primary-text-color); }
  .unit { font-size: 1.2rem; margin-left: 2px; color: var(--secondary-text-color); }
  .activity { display: flex; align-items: center; gap: 6px; font-size: 1rem; color: var(--primary-text-color); }
  .activity ha-icon { --mdc-icon-size: 20px; }
  .activity.charging ha-icon { color: var(--success-color, #43a047); }
  .activity.discharging ha-icon { color: var(--warning-color, #ffa600); }
  .activity.standby ha-icon { color: var(--secondary-text-color); }
  .power { color: var(--secondary-text-color); }
  .state { font-size: .9rem; color: var(--secondary-text-color); }
  .flows { display: grid; grid-template-columns: repeat(auto-fit, minmax(90px, 1fr)); gap: 8px; margin-top: 16px; }
  .flow { display: flex; flex-direction: column; gap: 2px; padding: 8px; border-radius: 12px; background: var(--secondary-background-color); }
  .flow ha-icon { --mdc-icon-size: 18px; color: var(--secondary-text-color); }
  .flow .label { font-size: .8rem; color: var(--secondary-text-color); }
  .flow .value { font-size: .95rem; color: var(--primary-text-color); }
  .control { margin-top: 16px; display: flex; flex-direction: column; gap: 8px; }
  .row { display: flex; justify-content: space-between; font-size: .9rem; }
  .row .label { color: var(--primary-text-color); font-weight: 500; }
  .ends { color: var(--secondary-text-color); }
  .segments { display: flex; border-radius: 12px; overflow: hidden; border: 1px solid var(--divider-color); }
  .segment { flex: 1; padding: 10px 6px; text-align: center; font-size: .9rem; color: var(--primary-text-color); }
  .segment + .segment { border-left: 1px solid var(--divider-color); }
  .segment.active { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  .segment:disabled { opacity: .5; cursor: default; }
  .warning { display: flex; align-items: center; gap: 6px; font-size: .9rem; color: var(--error-color, #db4437); }
  .warning ha-icon { --mdc-icon-size: 18px; }
  .missing { color: var(--secondary-text-color); }
</style>`;

if (!customElements.get(CARD)) {
  customElements.define(CARD, XoltaBatteryCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: CARD,
    name: "Ebbefos / Xolta battery",
    description: TEXT.en.description,
    preview: true,
    documentationURL: "https://github.com/Haulund83/home-assistant_xolta-modbus",
  });
  console.info(`%c XOLTA-BATTERY-CARD %c ${VERSION} `, "background:#2bb673;color:#fff", "");
}
