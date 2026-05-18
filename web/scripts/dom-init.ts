import { setVolume, stopAllButtonAudio, stopMainAudio } from "audio";
import {
  getButtonElement,
  getElement,
  getInputElement,
  getSelectElement,
} from "utils";

const SORT_ORDER_TITLES = {
  desc: "Sort direction (descending)",
  asc: "Sort direction (ascending)",
} as const;

const MEMBERS_TOGGLE_TITLES = {
  hidden: "Show group members",
  shown: "Hide group members",
} as const;

export function init() {
  const app = getElement("soundboard-app");
  const searchInput = getInputElement("input[type=search]");
  const sortSelect = getSelectElement("#sort");
  const sortOrderButton = getButtonElement("button#sort-order");
  const volumeSlider = getInputElement("input#volume");
  const stopButton = getButtonElement("button#stop");
  const clearFilterButton = getButtonElement("button#clear-filter");
  const playModeSingleButton = getButtonElement("button#play-mode-single");
  const playModeChaosButton = getButtonElement("button#play-mode-chaos");
  const membersToggleButton = getButtonElement("button#group-members-toggle");

  function setFilter(search: string) {
    app.setAttribute("filter", search);
    const filterActive = search.length > 0;
    membersToggleButton.dataset.filterActive = filterActive ? "true" : "false";
    if (filterActive) {
      membersToggleButton.title = "Filter is active — showing all matches";
    } else {
      const state = membersToggleButton.dataset.state === "shown"
        ? "shown"
        : "hidden";
      membersToggleButton.title = MEMBERS_TOGGLE_TITLES[state];
    }
  }

  function setSort(sortBy: string) {
    app.setAttribute("sort", sortBy);
  }

  function setSortOrder(order: "asc" | "desc") {
    app.setAttribute("sortorder", order);
    sortOrderButton.dataset.order = order;
    sortOrderButton.title = SORT_ORDER_TITLES[order];
  }

  function setSinglePlay(singlePlay: boolean) {
    app.setAttribute("singleplay", singlePlay ? "yes" : "no");
    playModeSingleButton.setAttribute(
      "aria-pressed",
      singlePlay ? "true" : "false"
    );
    playModeChaosButton.setAttribute(
      "aria-pressed",
      singlePlay ? "false" : "true"
    );
  }

  function setShowMembers(showMembers: boolean) {
    const state = showMembers ? "shown" : "hidden";
    app.setAttribute("showmembers", showMembers ? "yes" : "no");
    membersToggleButton.dataset.state = state;
    membersToggleButton.setAttribute("aria-label", MEMBERS_TOGGLE_TITLES[state]);
    membersToggleButton.setAttribute(
      "aria-pressed",
      showMembers ? "true" : "false"
    );
    if (membersToggleButton.dataset.filterActive !== "true") {
      membersToggleButton.title = MEMBERS_TOGGLE_TITLES[state];
    }
  }

  searchInput.addEventListener("input", () => {
    setFilter(searchInput.value);
    clearFilterButton.hidden = !searchInput.value;
  });

  clearFilterButton.addEventListener("click", () => {
    searchInput.value = "";
    setFilter("");
    clearFilterButton.hidden = true;
    searchInput.focus();
  });

  // Sticky detents
  const VOLUME_DETENTS = [100];
  const DETENT_THRESHOLD = 20;

  volumeSlider.addEventListener("input", () => {
    let value = parseInt(volumeSlider.value, 10);
    for (const detent of VOLUME_DETENTS) {
      if (Math.abs(value - detent) <= DETENT_THRESHOLD) {
        value = detent;
        volumeSlider.value = value.toString();
        break;
      }
    }
    setVolume(value);
  });

  stopButton.addEventListener("click", () => {
    stopMainAudio();
    stopAllButtonAudio();
  });

  playModeSingleButton.addEventListener("click", () => {
    stopAllButtonAudio();
    setSinglePlay(true);
  });

  playModeChaosButton.addEventListener("click", () => {
    setSinglePlay(false);
  });

  sortSelect.addEventListener("input", () => {
    setSort(sortSelect.value);
  });

  sortOrderButton.addEventListener("click", () => {
    const next = sortOrderButton.dataset.order === "asc" ? "desc" : "asc";
    setSortOrder(next);
  });

  membersToggleButton.addEventListener("click", () => {
    const showing = membersToggleButton.dataset.state === "shown";
    setShowMembers(!showing);
  });

  const initialOrder =
    sortOrderButton.dataset.order === "asc" ? "asc" : "desc";

  setFilter(searchInput.value ?? "");
  setSort(sortSelect.value ?? "");
  setSortOrder(initialOrder);
  setSinglePlay(true);
  setShowMembers(false);
}
