/* Reading aloud in Bangla and English (window.Speak), for the Reader (reader.js).

   The browser's own voices do the reading — nothing is sent anywhere. Most browsers have English voices, but
   a Bangla one only on some: Microsoft Edge (free online "Natural" Bangla voices), Android with Bangla installed
   in Google Text-to-speech, some others. So:

   - each sentence is split into its Bangla and English parts, and each part is read by a voice of its own
     language — "আজ Database Normalization পড়ব" is read half in Bangla, half in English;
   - the best voice of each language is picked by itself (a natural / online voice first), or the one chosen in
     the Reader's Aa panel (kept on this device);
   - with no Bangla voice, the Bangla parts can't be read: hasBangla() says so, and the Reader tells you how to
     get one, instead of an English voice mumbling through them.

   The voices are kept here, out of Alpine's reactive data: a voice wrapped by it isn't accepted by speak(). */
(function () {
  "use strict";
  var raw = [], listeners = [];
  var BN = /[ঀ-৿]/, EN = /[A-Za-z]/;

  function load() {
    if (!("speechSynthesis" in window)) return;
    raw = speechSynthesis.getVoices() || [];
    listeners.forEach(function (f) { f(); });
  }

  function langOf(v) { return /^bn/i.test(v.lang) ? "bn" : /^en/i.test(v.lang) ? "en" : ""; }

  function score(v, lang) {
    var n = v.name || "";
    return (/natural|neural|online|enhanced|premium/i.test(n) ? 8 : 0) + (/google/i.test(n) ? 4 : 0)
      + (lang === "bn" && /BD/i.test(v.lang) ? 2 : 0) + (lang === "en" && v["default"] ? 3 : 0)
      + (lang === "en" && /en[-_](US|GB)/i.test(v.lang) ? 1 : 0);
  }

  function list(lang) {
    return raw.filter(function (v) { return langOf(v) === lang; })
      .sort(function (a, b) { return score(b, lang) - score(a, lang) || a.name.localeCompare(b.name); });
  }

  /* The voice for a language: the chosen one (its voiceURI) if this device has it, else the best there is. */
  function pick(lang, uri) {
    var l = list(lang);
    return (uri && l.filter(function (v) { return v.voiceURI === uri; })[0]) || l[0] || null;
  }

  /* "আজ Database Normalization পড়ব।" → [{lang: "bn", text: "আজ "}, {lang: "en", text: "Database Normalization "}, {lang: "bn", text: "পড়ব।"}].
     Numbers, signs and spaces go with the words around them; a lone English word inside Bangla (or the other
     way round) stays with its neighbours when `merge` is set — fewer voice changes, for a voice that can read both. */
  function runs(text, merge) {
    var out = [], lead = "";
    (text.match(/\S+\s*/g) || []).forEach(function (tok) {
      var lang = BN.test(tok) ? "bn" : EN.test(tok) ? "en" : "";
      var last = out[out.length - 1];
      if (!lang) { if (last) last.text += tok; else lead += tok; return; }
      if (last && last.lang === lang) { last.text += tok; last.words++; return; }
      out.push({ lang: lang, text: lead + tok, words: 1 });
      lead = "";
    });
    if (!out.length) return text.trim() ? [{ lang: "en", text: text, words: 1 }] : [];
    if (lead) out[out.length - 1].text += lead;
    if (merge) {
      for (var i = 1; i < out.length - 1; i++) {
        if (out[i].words === 1 && out[i - 1].lang === out[i + 1].lang) {
          out[i - 1].text += out[i].text + out[i + 1].text;
          out[i - 1].words += 1 + out[i + 1].words;
          out.splice(i, 2);
          i--;
        }
      }
    }
    return out.map(function (r) { return { lang: r.lang, text: r.text }; });
  }

  /* What to say, in order: [{text, lang, voice}] — a part with no voice of its language is left out (skipped). */
  function plan(text, prefs) {
    prefs = prefs || {};
    var bn = pick("bn", prefs.voiceBn), en = pick("en", prefs.voiceEn);
    return runs(text, true).map(function (r) {
      var v = r.lang === "bn" ? bn : en;
      return { text: r.text, lang: r.lang, voice: v, skip: r.lang === "bn" && !bn && raw.length > 0 };
    });
  }

  function utter(part, rate) {
    var u = new SpeechSynthesisUtterance(part.text);
    u.rate = rate || 1;
    if (part.voice) { u.voice = part.voice; u.lang = part.voice.lang; }
    else u.lang = part.lang === "bn" ? "bn-BD" : "en-US";          // no list yet (some phones): the browser picks by language
    return u;
  }

  window.Speak = {
    ok: "speechSynthesis" in window,
    load: load,
    onChange: function (f) { listeners.push(f); },
    /* {uri, name, lang} for the Aa panel — plain objects, safe in Alpine. */
    choices: function (lang) { return list(lang).map(function (v) { return { uri: v.voiceURI, name: v.name, lang: v.lang }; }); },
    hasBangla: function () { return list("bn").length > 0; },
    known: function () { return raw.length > 0; },
    pick: pick, runs: runs, plan: plan, utter: utter,
    isBangla: function (text) { return BN.test(text || ""); },
    /* A short sample in both languages, with the voices chosen. */
    test: function (prefs, rate) {
      if (!("speechSynthesis" in window)) return;
      speechSynthesis.cancel();
      plan("আমি বাংলা পড়তে পারি। And I can read English too.", prefs).forEach(function (p) { if (!p.skip) speechSynthesis.speak(utter(p, rate)); });
    },
  };
  if ("speechSynthesis" in window) {
    load();
    if (speechSynthesis.addEventListener) speechSynthesis.addEventListener("voiceschanged", load);
    else speechSynthesis.onvoiceschanged = load;
    setTimeout(load, 1500);                                         // some browsers fill the list late and say nothing
  }
})();
