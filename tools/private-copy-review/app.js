/* Private blind copy-review form.
 * Offline and private: no network requests, no storage, no cookies, no eval and
 * no HTML parsing of supplied text (textContent only). The page never sees the
 * origin mapping; it exports a ballot the operator imports with the CLI.
 */
(function (root) {
  "use strict";

  var ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;
  var METRICS = ["punch", "clarity", "unnecessary_words"];
  var PREFERENCES = ["A", "B", "tie", "abstain"];
  var PREFERENCE_LABELS = { A: "Prefer A", B: "Prefer B", tie: "Tie", abstain: "Abstain" };
  var RATER_KINDS = ["human_assertion", "synthetic_fixture"];
  var NOTE_LIMIT = 2000;
  var BALLOT_SCHEMA = "theheat.copy-review-ballot/v1";
  var FORM_VERSION = "1";

  function emptyState(pack) {
    var pairs = {};
    pack.pairs.forEach(function (pair) {
      pairs[pair.pair_id] = { preference: null, scores: { A: {}, B: {} }, notes: "" };
    });
    return { raterId: "", raterKind: null, assertion: false, pairs: pairs };
  }

  function isScore(value) {
    return typeof value === "number" && Number.isInteger(value) && value >= 1 && value <= 5;
  }

  function anyScore(entry) {
    return ["A", "B"].some(function (side) {
      return METRICS.some(function (metric) { return entry.scores[side][metric] !== undefined; });
    });
  }

  /* Pure validation: returns ordered errors (with a target id) and the ratings to export. */
  function validate(state, pack) {
    var errors = [];
    var ratings = [];
    if (!ID.test(state.raterId)) {
      errors.push({ target: "rater-id", message: "Enter a rater ID using letters, digits, dot, dash, colon or underscore." });
    }
    if (RATER_KINDS.indexOf(state.raterKind) < 0) {
      errors.push({ target: "rater-kind-0", message: "Choose what kind of ratings these are." });
    }
    if (state.assertion !== true) {
      errors.push({ target: "rater-assertion", message: "Confirm that the kind you chose is true." });
    }
    pack.pairs.forEach(function (pair, index) {
      var entry = state.pairs[pair.pair_id];
      var label = "Pair " + (index + 1);
      if (entry.notes.length > NOTE_LIMIT) {
        errors.push({ target: "notes-" + index, message: label + ": notes are limited to " + NOTE_LIMIT + " characters." });
      }
      if (entry.preference === null) {
        if (anyScore(entry) || entry.notes.trim()) {
          errors.push({ target: "preference-" + index + "-A", message: label + ": choose a preference, or clear its scores and notes to leave it unrated." });
        }
        return;
      }
      if (PREFERENCES.indexOf(entry.preference) < 0) {
        errors.push({ target: "preference-" + index + "-A", message: label + ": unknown preference." });
        return;
      }
      var scores = { A: null, B: null };
      if (entry.preference !== "abstain") {
        ["A", "B"].forEach(function (side) {
          var row = {};
          METRICS.forEach(function (metric) {
            var value = entry.scores[side][metric];
            if (!isScore(value)) {
              errors.push({ target: "score-" + index + "-" + side + "-" + metric + "-1",
                message: label + ": score " + side + " " + metric.replace("_", " ") + " from 1 to 5." });
            }
            row[metric] = value;
          });
          scores[side] = row;
        });
      }
      ratings.push({ pair_id: pair.pair_id, pair_sha256: pair.pair_sha256, preference: entry.preference,
        scores: scores, notes: entry.notes });
    });
    if (!errors.length && !ratings.length) {
      errors.push({ target: "preference-0-A", message: "Rate at least one pair before downloading a ballot." });
    }
    return { errors: errors, ratings: ratings };
  }

  function buildBallot(state, pack, ratings, nowIso) {
    return {
      schema: BALLOT_SCHEMA, form_version: FORM_VERSION, pack_id: pack.pack_id, pack_sha256: pack.pack_sha256,
      rubric_id: pack.rubric.id, rubric_sha256: pack.rubric_sha256, rater_id: state.raterId,
      rater_kind: state.raterKind, rater_assertion: true, rated_at: nowIso, ratings: ratings
    };
  }

  function ballotFilename(pack, state) {
    return "ballot-" + pack.pack_id + "-" + state.raterId.replace(/[^A-Za-z0-9_.-]/g, "_") + ".json";
  }

  /* ------------------------------------------------------------------ DOM */

  function el(tag, attributes, text) {
    var node = document.createElement(tag);
    Object.keys(attributes || {}).forEach(function (name) { node.setAttribute(name, attributes[name]); });
    if (text !== undefined && text !== null) { node.textContent = String(text); }
    return node;
  }

  function radioGroup(legendText, name, idPrefix, options, onChoose) {
    var set = el("fieldset", { "class": "choices" });
    set.appendChild(el("legend", {}, legendText));
    options.forEach(function (option) {
      var id = idPrefix + "-" + option.value;
      var input = el("input", { type: "radio", name: name, value: String(option.value), id: id });
      input.addEventListener("change", function () { onChoose(option.value); });
      var label = el("label", { "for": id, "class": "pill" });
      label.appendChild(input);
      label.appendChild(document.createTextNode(" " + option.label));
      set.appendChild(label);
    });
    return set;
  }

  function renderRubric(pack) {
    var list = document.getElementById("rubric");
    METRICS.forEach(function (metric) {
      list.appendChild(el("dt", {}, metric.replace("_", " ")));
      list.appendChild(el("dd", {}, pack.rubric.scores[metric]));
    });
    list.appendChild(el("dt", {}, "preference"));
    list.appendChild(el("dd", {}, pack.rubric.preference));
    list.appendChild(el("dt", {}, "length"));
    list.appendChild(el("dd", {}, pack.rubric.length));
  }

  function renderPair(pack, pair, index, state) {
    var entry = state.pairs[pair.pair_id];
    var section = el("section", { "class": "panel pair", "aria-labelledby": "pair-title-" + index });
    section.appendChild(el("h2", { id: "pair-title-" + index }, "Pair " + (index + 1) + " of " + pack.pairs.length));
    section.appendChild(el("p", { "class": "context" }, pair.source_context));
    var q = pair.qualification;
    section.appendChild(el("p", { "class": "qualification" },
      "Evidence qualification (an assertion): " + q.status + " by " + q.adjudicator + " via " +
      q.method.replace(/_/g, " ") + " — " + q.reference));
    var grid = el("div", { "class": "sides" });
    ["A", "B"].forEach(function (side) {
      var data = pair.sides[side];
      var card = el("article", { "class": "side", "aria-labelledby": "side-" + index + "-" + side });
      card.appendChild(el("h3", { id: "side-" + index + "-" + side }, side));
      card.appendChild(el("blockquote", { "class": "copy" }, data.text));
      card.appendChild(el("p", { "class": "length" },
        data.characters + " characters, " + data.words + " words (descriptive only)"));
      METRICS.forEach(function (metric) {
        var options = [1, 2, 3, 4, 5].map(function (n) { return { value: n, label: String(n) }; });
        card.appendChild(radioGroup(side + " " + metric.replace("_", " ") + (metric === "unnecessary_words" ? " (higher is worse)" : ""),
          "score-" + index + "-" + side + "-" + metric, "score-" + index + "-" + side + "-" + metric, options,
          function (value) { entry.scores[side][metric] = value; }));
      });
      grid.appendChild(card);
    });
    section.appendChild(grid);
    section.appendChild(radioGroup("Preference", "preference-" + index, "preference-" + index,
      PREFERENCES.map(function (value) { return { value: value, label: PREFERENCE_LABELS[value] }; }),
      function (value) { entry.preference = value; }));
    var notesId = "notes-" + index;
    var field = el("div", { "class": "field" });
    field.appendChild(el("label", { "for": notesId }, "Notes (optional, private)"));
    var notes = el("textarea", { id: notesId, maxlength: String(NOTE_LIMIT), rows: "3" });
    var counter = el("p", { "class": "help", id: notesId + "-count" }, "0 / " + NOTE_LIMIT);
    notes.setAttribute("aria-describedby", notesId + "-count");
    notes.addEventListener("input", function () {
      entry.notes = notes.value;
      counter.textContent = notes.value.length + " / " + NOTE_LIMIT;
    });
    field.appendChild(notes);
    field.appendChild(counter);
    var clear = el("button", { type: "button", "class": "secondary" }, "Clear this pair");
    clear.addEventListener("click", function () {
      entry.preference = null;
      entry.scores = { A: {}, B: {} };
      entry.notes = "";
      notes.value = "";
      counter.textContent = "0 / " + NOTE_LIMIT;
      section.querySelectorAll("input[type=radio]").forEach(function (input) { input.checked = false; });
    });
    field.appendChild(clear);
    section.appendChild(field);
    return section;
  }

  function showErrors(errors) {
    var box = document.getElementById("errors");
    box.textContent = "";
    if (!errors.length) { return; }
    box.appendChild(el("p", {}, "Fix " + errors.length + (errors.length === 1 ? " problem" : " problems") + " before downloading:"));
    var list = el("ul", {});
    errors.forEach(function (error) {
      var item = el("li", {});
      var jump = el("button", { type: "button", "class": "link" }, error.message);
      jump.addEventListener("click", function () {
        var target = document.getElementById(error.target);
        if (target) { target.focus(); }
      });
      item.appendChild(jump);
      list.appendChild(item);
    });
    box.appendChild(list);
  }

  function download(ballot, filename) {
    var blob = new Blob([JSON.stringify(ballot, null, 1) + "\n"], { type: "application/json" });
    var url = URL.createObjectURL(blob);
    var link = el("a", { href: url, download: filename, "class": "hidden" });
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setTimeout(function () { URL.revokeObjectURL(url); }, 10000);
  }

  function init(pack) {
    var state = emptyState(pack);
    document.getElementById("pack-line").textContent = pack.pack_id + " · rubric " + pack.rubric.id;
    renderRubric(pack);
    var container = document.getElementById("pairs");
    pack.pairs.forEach(function (pair, index) { container.appendChild(renderPair(pack, pair, index, state)); });
    var raterId = document.getElementById("rater-id");
    raterId.addEventListener("input", function () { state.raterId = raterId.value; });
    document.querySelectorAll("input[name=rater-kind]").forEach(function (input, index) {
      input.id = "rater-kind-" + index;
      input.addEventListener("change", function () { state.raterKind = input.value; });
    });
    var assertion = document.getElementById("rater-assertion");
    assertion.addEventListener("change", function () { state.assertion = assertion.checked; });
    document.getElementById("export").addEventListener("click", function () {
      var result = validate(state, pack);
      var status = document.getElementById("status");
      showErrors(result.errors);
      if (result.errors.length) {
        status.textContent = "";
        document.getElementById("errors").focus();
        return;
      }
      var filename = ballotFilename(pack, state);
      download(buildBallot(state, pack, result.ratings, new Date().toISOString()), filename);
      status.textContent = "Downloaded " + filename + " with " + result.ratings.length + " rated pair" +
        (result.ratings.length === 1 ? "" : "s") + ". Import it with the private CLI.";
    });
    document.getElementById("errors").setAttribute("tabindex", "-1");
  }

  root.PrivateCopyReview = {
    validate: validate, buildBallot: buildBallot, emptyState: emptyState, ballotFilename: ballotFilename,
    METRICS: METRICS, PREFERENCES: PREFERENCES, BALLOT_SCHEMA: BALLOT_SCHEMA
  };
  if (typeof document !== "undefined" && root.PRIVATE_COPY_REVIEW_PACK) {
    init(root.PRIVATE_COPY_REVIEW_PACK);
  }
})(typeof window !== "undefined" ? window : globalThis);
