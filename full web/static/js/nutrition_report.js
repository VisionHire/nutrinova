/* Nutrition Report — final optimised version
   Features: fast suggestions, responsive, saved meals, detailed table + totals page in PDF
   Guaranteed no cuts: precise pixel-based chunking with safe margins
   Server-side saved meals: no LocalStorage, uses /api/saved-meals (last 30 days)
*/
(function () {
  // ----- DOM elements -----
  const rowsWrap = document.getElementById("rows");
  const addRowBtn = document.getElementById("addRow");
  const genBtn = document.getElementById("generate");
  const pdfBtn = document.getElementById("downloadPdf");
  const reportWrap = document.getElementById("reportWrap");
  const startEl = document.getElementById("startDate");
  const endEl = document.getElementById("endDate");
  const savedMealsSelect = document.getElementById("savedMealsSelect");
  const loadSavedBtn = document.getElementById("loadSaved");

  // ----- State -----
  let savedMealsCache = [];
  let foodsData = null; // raw food index
  let foodsWithNormalized = null; // pre‑normalised for O(1) lookups
  let foodsLoadPromise = null; // prevent parallel fetches
  let totalsData = null; // stored totals for PDF summary

  // ----- Inject CSS for suggestion box (handles long names) -----
  const style = document.createElement("style");
  style.textContent = `
    .food-wrap { position: relative; }
    .suggestions {
      position: absolute;
      top: 100%;
      left: 0;
      right: 0;
      background: white;
      border: 1px solid #ccc;
      border-top: none;
      max-height: 200px;
      overflow-y: auto;
      z-index: 1000;
      display: none;
      list-style: none;
      margin: 0;
      padding: 0;
      max-width: 400px;
      font-size: 12px;
    }
    .suggestions li {
      padding: 6px 10px;
      cursor: pointer;
      white-space: normal;
      word-break: break-word;
    }
    .suggestions li:hover {
      background-color: #f0f0f0;
    }
  `;
  document.head.appendChild(style);

  // ----- Helpers -----
  const pad2 = (n) => String(n).padStart(2, "0");
  const fmtDateShort = (d) =>
    `${pad2(d.getDate())}-${pad2(d.getMonth() + 1)}-${String(d.getFullYear()).slice(-2)}`;

  const today = new Date();

  // Normalise string for key matching (remove spaces, punctuation, lower case)
  const normalizeKey = (str) =>
    str
      .toLowerCase()
      .replace(/[\s_\-()]/g, "")
      .replace(/[^a-z0-9]/g, "");

  // ----- Preprocess foods: create normalised maps for macros, vitamins, minerals -----
  function preprocessFoods(foods) {
    const result = {};
    for (const [name, food] of Object.entries(foods)) {
      const normalized = {};

      if (food.macronutrients) {
        normalized.macros = {};
        for (const [key, value] of Object.entries(food.macronutrients)) {
          normalized.macros[normalizeKey(key)] = value;
        }
      }

      if (food.vitamins) {
        normalized.vitamins = {};
        for (const [key, value] of Object.entries(food.vitamins)) {
          normalized.vitamins[normalizeKey(key)] = value;
        }
      }

      if (food.minerals_and_trace) {
        normalized.minerals = {};
        for (const [key, value] of Object.entries(food.minerals_and_trace)) {
          normalized.minerals[normalizeKey(key)] = value;
        }
      }

      result[name.toLowerCase()] = {
        original: food,
        normalized,
      };
    }
    return result;
  }

  // ----- Load food index once (cached) -----
  async function loadFoodsIndex() {
    if (foodsData) return foodsData;
    if (foodsLoadPromise) return foodsLoadPromise;

    foodsLoadPromise = (async () => {
      const res = await fetch("/api/get_nutrition_data");
      if (!res.ok) throw new Error("Failed to load foods index");
      const raw = await res.json();
      foodsData = raw;
      foodsWithNormalized = preprocessFoods(raw);
      return raw;
    })();

    return foodsLoadPromise;
  }
  // Preload in background
  loadFoodsIndex().catch(console.error);

  // ----- Add a new row with autosuggest (debounced) -----
  function addRow(name = "", weight = "") {
    const line = document.createElement("div");
    line.className = "row-line";
    line.innerHTML = `
      <div class="food-wrap">
        <input type="text" class="food" placeholder="Food name (e.g., dosa)" value="${name}" autocomplete="off">
        <ul class="suggestions"></ul>
      </div>
      <input type="number" min="1" class="weight" placeholder="Weight (g)" value="${weight}">
      <button class="del" title="Remove">×</button>
    `;

    line.querySelector(".del").onclick = () => line.remove();
    rowsWrap.appendChild(line);

    const foodInput = line.querySelector(".food");
    const suggestionBox = line.querySelector(".suggestions");

    let debounceTimer;
    foodInput.addEventListener("input", () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(async () => {
        const query = foodInput.value.trim().toLowerCase();
        suggestionBox.innerHTML = "";
        if (!query) return;

        await loadFoodsIndex();
        const matches = Object.keys(foodsData)
          .filter((k) => k.toLowerCase().includes(query))
          .map((k) => ({ name: k, score: k.toLowerCase().indexOf(query) }))
          .sort((a, b) => {
            // exact start first, then earlier occurrence, then alphabetical
            if (a.score === 0 && b.score !== 0) return -1;
            if (b.score === 0 && a.score !== 0) return 1;
            if (a.score !== b.score) return a.score - b.score;
            return a.name.localeCompare(b.name);
          })
          .slice(0, 7)
          .map((item) => item.name);

        if (!matches.length) return;

        suggestionBox.style.display = "block";
        matches.forEach((item) => {
          const li = document.createElement("li");
          li.textContent = item;
          li.title = item; // show full name on hover
          li.addEventListener("click", () => {
            foodInput.value = item;
            suggestionBox.innerHTML = "";
            suggestionBox.style.display = "none";
          });
          suggestionBox.appendChild(li);
        });
      }, 200); // debounce 200ms
    });

    foodInput.addEventListener("blur", () => {
      setTimeout(() => (suggestionBox.style.display = "none"), 150);
    });
  }

  // Initialise with two empty rows
  addRow();
  addRow();

  // ----- Load saved meals (last 30 days) -----
  async function loadSavedMeals() {
    if (!savedMealsSelect) return;
    savedMealsSelect.innerHTML = `<option value="">Load from Saved Meals (Last 30 Days)</option>`;

    try {
      const res = await fetch("/api/saved-meals?days=30");
      if (!res.ok) throw new Error("Failed to load saved meals");
      savedMealsCache = await res.json();

      savedMealsCache.forEach((meal) => {
        const opt = document.createElement("option");
        const count = (meal.items || []).length;
        opt.value = meal.id;
        opt.textContent = `${meal.meal_type} (${meal.date}) — ${count} items`;
        savedMealsSelect.appendChild(opt);
      });
    } catch (err) {
      console.error("Error loading saved meals:", err);
    }
  }
  loadSavedMeals();

  // Load a saved meal into the builder
  loadSavedBtn.addEventListener("click", () => {
    const selectedId = savedMealsSelect.value;
    if (!selectedId) return;

    const meal = savedMealsCache.find(
      (m) => String(m.id) === String(selectedId),
    );
    if (!meal || !meal.items || !meal.items.length) return;

    rowsWrap.innerHTML = "";
    meal.items.forEach((it) => addRow(it.name, it.weight));
  });

  addRowBtn.addEventListener("click", () => addRow());

  // ----- Nutrition groups -----
  const MACROS = [
    ["Calories", "kcal", "calories"],
    ["Protein", "g", "protein"],
    ["Carbohydrates", "g", "carbohydrate"],
    ["Fats (Total)", "g", "total_fats"],
    ["Saturated Fat", "g", "saturated_fats"],
    ["Omega-3", "g", "omega_3"],
    ["Omega-6", "g", "omega_6"],
    ["Fiber", "g", "fiber"],
    ["Water", "g", "water"],
  ];

  const VITAMINS = [
    "Vitamin A",
    "Vitamin B1 (Thiamine)",
    "Vitamin B2 (Riboflavin)",
    "Vitamin B3 (Niacin)",
    "Vitamin B5 (Pantothenic Acid)",
    "Vitamin B6",
    "Vitamin B7 (Biotin)",
    "Vitamin B9 (Folate)",
    "Vitamin B12",
    "Vitamin C",
    "Vitamin D",
    "Vitamin E",
    "Vitamin K",
    "Choline",
  ];

  const MINERALS = [
    "Calcium",
    "Iron",
    "Magnesium",
    "Phosphorus",
    "Potassium",
    "Sodium",
    "Zinc",
    "Iodine",
    "Selenium",
    "Copper",
    "Manganese",
    "Chromium",
    "Molybdenum",
    "Fluoride",
  ];

  const scale = (val, weight) =>
    Math.round((+val || 0) * (weight / 100) * 100) / 100;

  const parseValueAndUnit = (v) => {
    if (!v) return { num: 0, unit: "" };
    const match = String(v)
      .trim()
      .match(/^([\d.]+)\s*([a-zA-ZµμIU%]*)$/);
    if (match) return { num: parseFloat(match[1]), unit: match[2] || "" };
    const num = parseFloat(String(v).replace(/[^\d.]/g, "")) || 0;
    const unit = String(v).replace(/[\d.\s]/g, "") || "";
    return { num, unit };
  };

  // ----- Build on‑screen table (only main table, no summary inside) -----
  function buildScreenTable(items) {
    const from = startEl.value ? new Date(startEl.value) : null;
    const to = endEl.value ? new Date(endEl.value) : null;
    const dateStr =
      from && to
        ? `Date : ${fmtDateShort(from)} — ${fmtDateShort(to)}`
        : "Date : Not selected";

    reportWrap.innerHTML = `
      <div class="caption">
        <div class="date">${dateStr}</div>
        <div class="title-lg">Food Nutrition Report</div>
      </div>
      <div class="table-scroll">
        <table class="report" id="screenReport">
          <thead></thead><tbody></tbody>
        </table>
      </div>
    `;

    const thead = reportWrap.querySelector("thead");
    const tbody = reportWrap.querySelector("tbody");
    const colCount = items.length;

    // Header row 1
    const tr1 = document.createElement("tr");
    tr1.innerHTML = `<th rowspan="2" class="left">Nutrition</th><th colspan="${colCount}">Food Items</th>`;
    thead.appendChild(tr1);

    // Header row 2: food names + weight below
    const tr2 = document.createElement("tr");
    items.forEach((item) => {
      tr2.innerHTML += `<th>${item.name}<br><span style="font-weight:normal;font-size:0.8em;">${item.weight} g</span></th>`;
    });
    thead.appendChild(tr2);

    // Helper: get scaled value and numeric value from pre‑normalised data
    const getScaled = (
      food,
      category,
      normalizedLabel,
      weight,
      defaultUnit = "g",
    ) => {
      if (!food) return { display: "—", num: 0 };
      const norm =
        foodsWithNormalized[food]?.normalized[category]?.[normalizedLabel];
      if (norm === undefined) return { display: "Trace", num: 0 };
      const parsed = parseValueAndUnit(norm);
      const scaled = parsed.num > 0 ? scale(parsed.num, weight) : 0;
      const unit = parsed.unit || defaultUnit;
      return {
        display: scaled > 0 ? `${scaled.toFixed(2)} ${unit}` : "Trace",
        num: scaled,
      };
    };

    const rowGroupLabel = (label) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td class="left" colspan="${colCount + 1}" style="background:#f9fbf9;font-weight:600;">${label}</td>`;
      tbody.appendChild(tr);
    };

    // Totals accumulators
    const macroTotals = new Array(MACROS.length).fill(0);
    const vitaminTotals = new Array(VITAMINS.length).fill(0);
    const mineralTotals = new Array(MINERALS.length).fill(0);

    // ----- Macronutrients -----
    rowGroupLabel("Macronutrients");
    MACROS.forEach(([label, unit, key], idx) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td class="left">${label}</td>`;
      const normKey = normalizeKey(key);
      items.forEach(({ name, weight }) => {
        const foodKey = name.toLowerCase();
        const food = foodsWithNormalized[foodKey];
        if (!food) {
          tr.innerHTML += `<td>—</td>`;
          return;
        }
        const result = getScaled(foodKey, "macros", normKey, weight, unit);
        tr.innerHTML += `<td>${result.display}</td>`;
        macroTotals[idx] += result.num;
      });
      tbody.appendChild(tr);
    });

    // ----- Vitamins -----
    rowGroupLabel("Vitamins");
    VITAMINS.forEach((label, idx) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td class="left">${label}</td>`;
      const normLabel = normalizeKey(label);
      items.forEach(({ name, weight }) => {
        const foodKey = name.toLowerCase();
        const food = foodsWithNormalized[foodKey];
        if (!food) {
          tr.innerHTML += `<td>—</td>`;
          return;
        }
        const result = getScaled(foodKey, "vitamins", normLabel, weight, "mg");
        tr.innerHTML += `<td>${result.display}</td>`;
        vitaminTotals[idx] += result.num;
      });
      tbody.appendChild(tr);
    });

    // ----- Minerals -----
    rowGroupLabel("Minerals and Trace Elements");
    MINERALS.forEach((label, idx) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td class="left">${label}</td>`;
      const normLabel = normalizeKey(label);
      items.forEach(({ name, weight }) => {
        const foodKey = name.toLowerCase();
        const food = foodsWithNormalized[foodKey];
        if (!food) {
          tr.innerHTML += `<td>—</td>`;
          return;
        }
        const result = getScaled(foodKey, "minerals", normLabel, weight, "mg");
        tr.innerHTML += `<td>${result.display}</td>`;
        mineralTotals[idx] += result.num;
      });
      tbody.appendChild(tr);
    });

    // Store totals for PDF summary page
    totalsData = { macroTotals, vitaminTotals, mineralTotals };

    // ----- Horizontal scrolling for mobile (unchanged) -----
    const tableScroll = reportWrap.querySelector(".table-scroll");
    if (tableScroll) {
      tableScroll.style.overflowX = "auto";
      tableScroll.style.overflowY = "hidden";
      tableScroll.style.webkitOverflowScrolling = "touch";
      tableScroll.style.scrollBehavior = "smooth";
      tableScroll.style.touchAction = "pan-x";

      let startX = 0,
        startY = 0,
        isPanningX = false;
      tableScroll.addEventListener(
        "touchstart",
        (e) => {
          startX = e.touches[0].clientX;
          startY = e.touches[0].clientY;
          isPanningX = false;
        },
        { passive: true },
      );

      tableScroll.addEventListener(
        "touchmove",
        (e) => {
          const dx = e.touches[0].clientX - startX;
          const dy = e.touches[0].clientY - startY;
          if (!isPanningX) {
            isPanningX = Math.abs(dx) > Math.abs(dy) + 6;
          }
          if (isPanningX) {
            e.preventDefault();
            tableScroll.scrollLeft -= dx;
            startX = e.touches[0].clientX;
          }
        },
        { passive: false },
      );

      tableScroll.addEventListener(
        "wheel",
        (e) => {
          if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
            tableScroll.scrollLeft += e.deltaY;
            e.preventDefault();
          }
        },
        { passive: false },
      );
    }
  }

  // ----- Generate report -----
  genBtn.addEventListener("click", async () => {
    const startDate = startEl.value ? new Date(startEl.value) : today;
    const endDate = endEl.value ? new Date(endEl.value) : today;

    const manualItems = [...rowsWrap.querySelectorAll(".row-line")]
      .map((r) => ({
        name: r.querySelector(".food").value.trim(),
        weight: +r.querySelector(".weight").value || 0,
      }))
      .filter((x) => x.name && x.weight > 0);

    const mealsInRange = (savedMealsCache || [])
      .filter((m) => {
        if (!m.date) return false;
        const d = new Date(m.date);
        return d >= startDate && d <= endDate;
      })
      .flatMap((m) =>
        (m.items || []).map((i) => ({
          name: i.name,
          weight: +i.weight || 0,
        })),
      );

    const combinedItems = [...manualItems, ...mealsInRange];
    if (!combinedItems.length) {
      alert("No meals found in selected range or added manually.");
      return;
    }

    await loadFoodsIndex(); // ensure data is loaded
    buildScreenTable(combinedItems);
    pdfBtn.disabled = false;
  });

  // ----- PDF export: main table + totals table (as HTML) -----
  pdfBtn.addEventListener("click", async () => {
    if (pdfBtn.disabled) return;

    // Load libraries if not already present
    if (!window.html2canvas)
      await import("https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js");
    if (!window.jspdf)
      await import("https://cdn.jsdelivr.net/npm/jspdf@2.5.1/dist/jspdf.umd.min.js");
    const { jsPDF } = window.jspdf;

    const user =
      reportWrap.dataset.currentUser || window.CURRENT_USER_NAME || "User";
    const start = startEl.value ? new Date(startEl.value) : new Date();
    const end = endEl.value ? new Date(endEl.value) : new Date();
    const dateStr = `${fmtDateShort(start)} — ${fmtDateShort(end)}`;

    // ----- MAIN TABLE (clone and render at natural width) -----
    const orig = document.querySelector("#reportWrap");
    if (!orig) return alert("No report to export!");

    const mainClone = orig.cloneNode(true);
    // Remove any existing summary (should not exist, but safe)
    const existingSummary = mainClone.querySelector(".summary-section");
    if (existingSummary) existingSummary.remove();

    mainClone.style.position = "absolute";
    mainClone.style.left = "-9999px";
    mainClone.style.top = "0";
    mainClone.style.width = "max-content";
    mainClone.style.maxWidth = "none";
    mainClone.style.height = "auto";
    mainClone.style.overflow = "visible";
    document.body.appendChild(mainClone);

    // Add styling for better PDF readability
    const mainStyle = document.createElement("style");
    mainStyle.textContent = `
      table.report { border-collapse: collapse; width: 100%; }
      table.report th, table.report td { border: 1px solid #ccc; padding: 6px; text-align: center; }
      table.report th { white-space: normal; word-break: break-word; }
      table.report td.left { text-align: left; }
      table.report tbody tr:nth-child(even) { background-color: #f9f9f9; }
    `;
    mainClone.appendChild(mainStyle);

    const mainCanvas = await html2canvas(mainClone, {
      scale: 1.5,
      useCORS: true,
      backgroundColor: "#ffffff",
      scrollX: 0,
      scrollY: 0,
      windowWidth: mainClone.scrollWidth,
      windowHeight: mainClone.scrollHeight,
    });
    document.body.removeChild(mainClone);

    // ----- TOTALS TABLE (create a clean HTML table) -----
    const totalsDiv = document.createElement("div");
    totalsDiv.style.position = "absolute";
    totalsDiv.style.left = "-9999px";
    totalsDiv.style.top = "0";
    totalsDiv.style.width = "800px";
    totalsDiv.style.backgroundColor = "#ffffff";
    totalsDiv.style.padding = "20px";
    totalsDiv.style.fontFamily = "Helvetica, Arial, sans-serif";

    let totalsHtml = `
      <style>
        .totals-table {
          border-collapse: collapse;
          width: 100%;
          font-size: 9pt;
        }
        .totals-table th {
          background-color: #e0e0e0;
          padding: 8px;
          text-align: left;
          border: 1px solid #aaa;
        }
        .totals-table td {
          padding: 6px;
          border: 1px solid #aaa;
          vertical-align: top;
        }
        .totals-table tr:nth-child(even) {
          background-color: #f9f9f9;
        }
        .totals-table .section-header td {
          background-color: #d0d0d0;
          font-weight: bold;
          padding: 6px 8px;
        }
        .totals-table td:first-child {
          width: 70%;
          white-space: normal;
          word-break: break-word;
        }
        .totals-table td:last-child {
          width: 30%;
          white-space: nowrap;
        }
      </style>
      <h2 style="text-align:center; margin-bottom:5px;">Nutrition Summary</h2>
      <p style="text-align:center; margin-top:0; font-size:10pt;">User: ${user} | Date: ${dateStr}</p>
      <table class="totals-table">
        <thead><tr><th>Nutrient</th><th>Total</th></tr></thead>
        <tbody>
    `;

    if (totalsData) {
      const { macroTotals, vitaminTotals, mineralTotals } = totalsData;

      totalsHtml += `<tr class="section-header"><td colspan="2">Macronutrients</td></tr>`;
      MACROS.forEach(([label, unit], idx) => {
        totalsHtml += `<tr><td>${label}</td><td>${macroTotals[idx].toFixed(2)} ${unit}</td></tr>`;
      });

      totalsHtml += `<tr class="section-header"><td colspan="2">Vitamins</td></tr>`;
      VITAMINS.forEach((label, idx) => {
        totalsHtml += `<tr><td>${label}</td><td>${vitaminTotals[idx].toFixed(2)} mg</td></tr>`;
      });

      totalsHtml += `<tr class="section-header"><td colspan="2">Minerals</td></tr>`;
      MINERALS.forEach((label, idx) => {
        totalsHtml += `<tr><td>${label}</td><td>${mineralTotals[idx].toFixed(2)} mg</td></tr>`;
      });
    } else {
      totalsHtml += `<tr><td colspan="2">No data</td></tr>`;
    }

    totalsHtml += `</tbody></table>`;
    totalsDiv.innerHTML = totalsHtml;
    document.body.appendChild(totalsDiv);

    const totalsCanvas = await html2canvas(totalsDiv, {
      scale: 1.5,
      useCORS: true,
      backgroundColor: "#ffffff",
      scrollX: 0,
      scrollY: 0,
    });
    document.body.removeChild(totalsDiv);

    // ----- PDF assembly with precise pixel-based chunking (no cuts) -----
    const pdf = new jsPDF({
      orientation: "portrait",
      unit: "pt",
      format: "a4",
    });
    const pageWidth = pdf.internal.pageSize.getWidth();
    const pageHeight = pdf.internal.pageSize.getHeight();
    const leftMargin = 30;
    const rightMargin = 30;
    const imgWidth = pageWidth - leftMargin - rightMargin;

    /**
     * Adds a canvas image to the PDF, splitting across pages if necessary.
     * Uses exact pixel calculations to ensure no content is lost.
     * @param {HTMLCanvasElement} canvas - The canvas to add.
     * @param {number} startY - Y position of image on first page.
     * @param {boolean} firstPageHasHeader - Whether first page already has title/user/date.
     */
    const addImagePages = (canvas, startY = 100, firstPageHasHeader = true) => {
      const totalPixels = canvas.height;
      const scaleFactor = imgWidth / canvas.width; // points per pixel

      let offsetY = 0; // pixels
      let pageNum = 0;

      while (offsetY < totalPixels) {
        const hasHeader = pageNum === 0 && firstPageHasHeader;
        const imageTop = hasHeader ? startY : 40;
        const bottomMargin = 35; // increased for safety
        const maxImageHeightPts = pageHeight - imageTop - bottomMargin;
        const maxImageHeightPx = Math.floor(maxImageHeightPts / scaleFactor); // pixels that fit

        // Height of this chunk in pixels (cannot exceed remaining)
        const chunkPixels = Math.min(maxImageHeightPx, totalPixels - offsetY);
        const chunkPoints = chunkPixels * scaleFactor;

        const pageCanvas = document.createElement("canvas");
        pageCanvas.width = canvas.width;
        pageCanvas.height = chunkPixels;
        const ctx = pageCanvas.getContext("2d");
        ctx.drawImage(
          canvas,
          0,
          offsetY,
          canvas.width,
          chunkPixels,
          0,
          0,
          canvas.width,
          chunkPixels,
        );
        const data = pageCanvas.toDataURL("image/png");
        pdf.addImage(data, "PNG", leftMargin, imageTop, imgWidth, chunkPoints);

        offsetY += chunkPixels;
        if (offsetY < totalPixels) {
          pdf.addPage();
          pageNum++;
        }
      }
    };

    // First page header
    pdf.setFont("helvetica", "bold");
    pdf.setFontSize(18);
    pdf.text("Food Nutrition Report", pageWidth / 2, 50, { align: "center" });
    pdf.setFont("helvetica", "normal");
    pdf.setFontSize(11);
    pdf.text(`User : ${user}`, 60, 70);
    pdf.text(`Date : ${dateStr}`, 60, 85);

    // Add main table pages (first page already has header)
    addImagePages(mainCanvas, 100, true);

    // Add totals page – canvas already contains its own header
    pdf.addPage();
    addImagePages(totalsCanvas, 40, false); // start near top, no PDF header

    // Page numbers
    const totalPages = pdf.internal.getNumberOfPages();
    for (let i = 1; i <= totalPages; i++) {
      pdf.setPage(i);
      pdf.setFontSize(9);
      pdf.setTextColor(120);
      pdf.text(`Page ${i} of ${totalPages}`, pageWidth - 80, pageHeight - 20);
    }

    pdf.save(
      `Nutrition_Report_${user.replace(/\s+/g, "_")}_${fmtDateShort(new Date())}.pdf`,
    );
  });
})();
