import { setVolume, stopAllButtonAudio, stopMainAudio } from "audio";
import {
  getButtonElement,
  getElement,
  getInputElement,
  getInputElements,
  getSelectElement,
} from "utils";

export function init() {
  const app = getElement("soundboard-app");
  const searchInput = getInputElement("input[type=search]");
  const sortSelect = getSelectElement("#sort");
  const singlePlayCheckbox = getInputElement("input#single-sound");
  const volumeSlider = getInputElement("input#volume");
  const stopButton = getButtonElement("button#stop");
  const sortOrderRadios = getInputElements("input[name=sortorder]");

  function getSelectedSortOrderRadio() {
    return Array.from(sortOrderRadios).find((radio) =>
      radio.matches(":checked")
    );
  }

  function setFilter(search: string) {
    app.setAttribute("filter", search);
  }

  function setSort(sortBy: string) {
    app.setAttribute("sort", sortBy);
  }

  function setSortOrder(order: string) {
    app.setAttribute("sortorder", order);
  }

  function setSinglePlay(singlePlay: boolean) {
    app.setAttribute("singleplay", singlePlay ? "yes" : "no");
  }

  searchInput.addEventListener("input", () => {
    setFilter(searchInput.value);
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

  singlePlayCheckbox.addEventListener("input", () => {
    if (singlePlayCheckbox.matches(":checked")) {
      stopAllButtonAudio();
      if (stopButton) stopButton.innerText = "Stop";
      setSinglePlay(true);
    } else {
      if (stopButton) stopButton.innerText = "Stop All";
      setSinglePlay(false);
    }
  });

  sortSelect.addEventListener("input", () => {
    setSort(sortSelect.value);
  });

  document.querySelectorAll("input[name=sortorder]").forEach((radiobox) => {
    radiobox.addEventListener("input", (e) => {
      setSortOrder((e.currentTarget as HTMLInputElement).value);
    });
  });

  setFilter(searchInput.value ?? "");
  setSort(sortSelect.value ?? "");
  setSortOrder(getSelectedSortOrderRadio()?.value ?? "");
  setSinglePlay(!!singlePlayCheckbox.matches(":checked"));
}
