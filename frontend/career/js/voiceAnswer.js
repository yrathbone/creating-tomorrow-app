// Speak-your-answer for the resume interview: on-device speech-to-text only, typed answers always available.
//
// Rules (Jo, 2026-11-22):
// - processLocally is set to true and never to false. If the browser will not confirm on-device mode, the mic is not offered.
// - Nothing starts without the member's click. Nothing is recorded, uploaded or stored: no MediaRecorder, no audio, no fetch.
// - The transcript goes into the answer box only. The existing "Continue" button is still what sends answers, as for typed text.
// - A language pack is never downloaded automatically. install() runs only from a click, and only when available() says "downloadable".
//
// Sources (read 2026-11-22):
// - MDN SpeechRecognition.processLocally: https://developer.mozilla.org/en-US/docs/Web/API/SpeechRecognition/processLocally
// - MDN Web Speech API (security, Permissions-Policy): https://developer.mozilla.org/en-US/docs/Web/API/Web_Speech_API
// - MDN SpeechRecognition.available(): https://developer.mozilla.org/en-US/docs/Web/API/SpeechRecognition/available_static
// - MDN SpeechRecognition.install(): https://developer.mozilla.org/en-US/docs/Web/API/SpeechRecognition/install_static
// Loaded by login.html before resumeReview.js. Tests: backend/tests/frontend/voice_answer.test.js.

(function (root) {
  "use strict";

  var DEFAULT_LANG = "en-US";

  // Only the unprefixed constructor is used. Prefixed webkit support is not used because it has no proven on-device mode here.
  function getRecognitionCtor(win) {
    var SR = win && win.SpeechRecognition;
    if (typeof SR !== "function") return null;
    if (typeof SR.available !== "function" || typeof SR.install !== "function") return null;
    return SR;
  }

  // Asks the browser whether on-device recognition for this language is ready. Resolves one of:
  // "available" | "downloadable" | "downloading" | "unavailable" | "unsupported" (no API) | "error".
  function checkOnDevice(SR, lang) {
    if (!SR) return Promise.resolve("unsupported");
    var langs = [lang || DEFAULT_LANG];
    try {
      return Promise.resolve(SR.available({ langs: langs, processLocally: true })).then(
        function (status) {
          return typeof status === "string" ? status : "error";
        },
        function () { return "error"; }
      );
    } catch (e) {
      return Promise.resolve("error");
    }
  }

  // Installs the language pack. Must be called from a click handler (transient activation); MDN: install() rejects without it.
  function installPack(SR, lang) {
    if (!SR) return Promise.resolve(false);
    try {
      return Promise.resolve(SR.install({ langs: [lang || DEFAULT_LANG] })).then(
        function (ok) { return ok === true; },
        function () { return false; }
      );
    } catch (e) {
      return Promise.resolve(false);
    }
  }

  // Maps a recognition error code to a message the member can act on. Never falls back to remote recognition.
  function errorMessage(code) {
    switch (code) {
      case "not-allowed":
      case "service-not-allowed":
        return "Microphone access was blocked, or the on-device speech pack is not allowed here. You can type your answer instead.";
      case "no-speech":
        return "No speech was heard. Try again, or type your answer.";
      case "audio-capture":
        return "No microphone was found. You can type your answer instead.";
      case "language-not-supported":
      case "language-unavailable":
        return "Speech for this language is not available on this device. You can type your answer instead.";
      case "aborted":
        return "Listening was stopped.";
      default:
        return "Speech input stopped with an error. You can type your answer instead.";
    }
  }

  // Creates a controller bound to one textarea. Nothing is started here: start() must be called from a click.
  // deps.SR is the recognition constructor; deps.onState(state, message) updates the button; deps.onFinal(text) appends text.
  function createVoiceInput(deps) {
    var SR = deps && deps.SR;
    var lang = (deps && deps.lang) || DEFAULT_LANG;
    var onState = (deps && deps.onState) || function () {};
    var onFinal = (deps && deps.onFinal) || function () {};
    var rec = null;
    var cancelled = false;
    var listening = false;

    function fail(message) {
      listening = false;
      rec = null;
      onState("idle", message || "");
    }

    // start() returns true only if recognition actually started with processLocally === true.
    function start() {
      if (listening) return false;
      if (!SR) { onState("idle", "Speech input is not available in this browser. You can type your answer instead."); return false; }
      var candidate;
      try {
        candidate = new SR();
        candidate.lang = lang;
        candidate.continuous = true;
        candidate.interimResults = true;
        candidate.processLocally = true;
      } catch (e) {
        fail("Speech input could not start. You can type your answer instead.");
        return false;
      }
      if (candidate.processLocally !== true) {
        // The browser did not keep the on-device setting: refuse rather than run remote recognition.
        fail("Speech input is not confirmed to run on this device, so it is off. You can type your answer instead.");
        return false;
      }
      rec = candidate;
      cancelled = false;
      rec.onresult = function (event) {
        if (cancelled) return;
        var interim = "";
        for (var i = event.resultIndex; i < event.results.length; i++) {
          var result = event.results[i];
          if (result.isFinal) {
            onFinal(result[0].transcript);
          } else {
            interim += result[0].transcript;
          }
        }
        if (interim) onState("listening", "Hearing: " + interim);
      };
      rec.onerror = function (event) {
        if (cancelled) return;
        fail(errorMessage(event && event.error));
      };
      rec.onend = function () {
        listening = false;
        rec = null;
        if (!cancelled) onState("idle", "");
      };
      try {
        rec.start();
      } catch (e) {
        fail("Speech input could not start. You can type your answer instead.");
        return false;
      }
      listening = true;
      onState("listening", "Listening on this device. Press Stop when you are done.");
      return true;
    }

    // stop(): keep what was heard so far (final results already appended).
    function stop() {
      if (rec) { try { rec.stop(); } catch (e) { /* already ended */ } }
    }

    // cancel(): discard anything not yet appended.
    function cancel() {
      cancelled = true;
      if (rec) { try { rec.abort(); } catch (e) { /* already ended */ } }
      listening = false;
      rec = null;
      onState("idle", "Listening was cancelled.");
    }

    return { start: start, stop: stop, cancel: cancel, isListening: function () { return listening; } };
  }

  // Adds text to the end of the answer box. Typed text already there is kept. Does not save anything.
  function appendTranscript(current, heard) {
    var add = (heard || "").trim();
    if (!add) return current || "";
    var base = (current || "").replace(/\s+$/, "");
    return base ? base + " " + add : add;
  }

  var api = {
    DEFAULT_LANG: DEFAULT_LANG,
    getRecognitionCtor: getRecognitionCtor,
    checkOnDevice: checkOnDevice,
    installPack: installPack,
    createVoiceInput: createVoiceInput,
    appendTranscript: appendTranscript,
    errorMessage: errorMessage,
  };
  root.VoiceAnswer = api;
})(typeof window !== "undefined" ? window : this);
