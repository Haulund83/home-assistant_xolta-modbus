// Renders the battery card with a minimal DOM stub (run by tests/test_card.py with node).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const registry = {};
globalThis.window = globalThis;
globalThis.HTMLElement = class {
  attachShadow() {
    this.shadowRoot = { innerHTML: "", querySelectorAll: () => [] };
    return this.shadowRoot;
  }
  dispatchEvent() {}
};
globalThis.customElements = {
  get: (name) => registry[name],
  define: (name, cls) => {
    registry[name] = cls;
  },
};
globalThis.console.info = () => {};

const file = new URL("../custom_components/xolta_modbus/card/xolta-battery-card.js", import.meta.url);
// eslint-disable-next-line no-eval
(0, eval)(readFileSync(file, "utf8"));
const Card = registry["xolta-battery-card"];
assert.ok(Card, "card is registered");

const entity = (entity_id, translation_key) => ({ entity_id, translation_key, platform: "xolta_modbus" });
const states = {
  "sensor.soc": { entity_id: "sensor.soc", state: "36", last_updated: "t1" },
  "sensor.activity": { entity_id: "sensor.activity", state: "standby", last_updated: "t1" },
  "sensor.state": { entity_id: "sensor.state", state: "running", last_updated: "t1" },
};
const entities = {
  "sensor.soc": entity("sensor.soc", "state_of_charge"),
  "sensor.activity": entity("sensor.activity", "activity"),
  "sensor.state": entity("sensor.state", "state"),
};
const hass = (format) => ({ language: "en", locale: { language: "en" }, states, entities, formatEntityState: format });

const card = new Card();
card.setConfig({});

// Translations not loaded yet: Home Assistant returns the raw state.
card.hass = hass((s) => s.state);
assert.match(card.shadowRoot.innerHTML, />standby</);

// Translations loaded: same states, new formatter. The card must redraw.
card.hass = hass((s) => ({ standby: "Standby", running: "Running" })[s.state] ?? s.state);
assert.match(card.shadowRoot.innerHTML, />Standby</);
assert.match(card.shadowRoot.innerHTML, />Running</);

// Nothing changed: no redraw (the shadow root content is left alone).
card.shadowRoot.innerHTML = "untouched";
card.hass = hass((s) => ({ standby: "Standby", running: "Running" })[s.state] ?? s.state);
assert.equal(card.shadowRoot.innerHTML, "untouched");

console.log("card render ok");
