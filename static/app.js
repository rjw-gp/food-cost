function initApp() {
  const recipeBody = document.getElementById('recipe-body');
  const rowTemplate = document.getElementById('row-template');
  const addRowButton = document.getElementById('add-row');
  const totalButton = document.getElementById('calculate-total');
  const recipeForm = document.getElementById('recipe-form');
  const ingredientForm = document.getElementById('ingredient-form');
  const results = document.getElementById('results');

  const UNIT_FACTORS = {
    'pounds': ['weight', 16.0],
    'ounces': ['weight', 1.0],
    'fluid ounces': ['volume', 29.5735],
    'milliliters': ['volume', 1.0],
    'liters': ['volume', 1000.0],
    'quarts': ['volume', 946.353],
    'gallons': ['volume', 3785.41],
    'each': ['count', 1.0],
  };

  function money(value) {
    return `$${Number(value).toFixed(2)}`;
  }

  function convertQuantity(quantity, fromUnit, toUnit) {
    const from = UNIT_FACTORS[fromUnit];
    const to = UNIT_FACTORS[toUnit];
    if (!from || !to) throw new Error('Unsupported unit');
    const [fromGroup, fromFactor] = from;
    const [toGroup, toFactor] = to;
    if (fromGroup !== toGroup) throw new Error(`Cannot convert ${fromUnit} to ${toUnit}`);
    return (quantity * fromFactor) / toFactor;
  }

  function calculateRow(row) {
    const epQty = Number(row.querySelector('.ep-quantity').value || 0);
    const epUnit = row.querySelector('.ep-unit').value;
    const yieldPercent = Number(row.querySelector('.yield-percent').value || 0);
    const apQty = Number(row.querySelector('.ap-quantity').value || 0);
    const apUnit = row.querySelector('.ap-unit').value;
    const apPrice = Number(row.querySelector('.ap-price').value || 0);

    if (!epQty || !yieldPercent || !apQty || !apPrice) {
      row.querySelector('.ap-cost-unit').textContent = '$0.00';
      row.querySelector('.ep-cost-unit').textContent = '$0.00';
      row.querySelector('.extended-cost').textContent = '$0.00';
      row.dataset.extendedCost = '0';
      return;
    }

    try {
      const convertedAP = convertQuantity(apQty, apUnit, epUnit);
      const apCost = apPrice / convertedAP;
      const epCost = apCost / (yieldPercent / 100);
      const extended = epCost * epQty;
      row.querySelector('.ap-cost-unit').textContent = money(apCost);
      row.querySelector('.ep-cost-unit').textContent = money(epCost);
      row.querySelector('.extended-cost').textContent = money(extended);
      row.dataset.extendedCost = String(extended);
    } catch (error) {
      row.querySelector('.ap-cost-unit').textContent = 'N/A';
      row.querySelector('.ep-cost-unit').textContent = 'N/A';
      row.querySelector('.extended-cost').textContent = 'N/A';
      row.dataset.extendedCost = '0';
    }
  }

  function calculateTotals() {
    const portions = Number(recipeForm.querySelector('[name="portions"]').value || 0);
    const spiceFactorPercent = Number(recipeForm.querySelector('[name="spice_factor_percent"]').value || 0);

    const totalCost = [...recipeBody.querySelectorAll('tr')].reduce((sum, row) => {
      return sum + Number(row.dataset.extendedCost || 0);
    }, 0);

    const costPerPortion = portions > 0 ? totalCost / portions : 0;
    const totalWithSpice = costPerPortion + (costPerPortion * (spiceFactorPercent / 100));

    results.innerHTML = `
      Total cost: ${money(totalCost)}<br>
      Cost per portion: ${money(costPerPortion)}<br>
      Total with spice factor adjustment: ${money(totalWithSpice)}
    `;
  }

  function bindRowEvents(row) {
    row.querySelectorAll('input, select').forEach((el) => {
      el.addEventListener('input', () => calculateRow(row));
      el.addEventListener('change', () => calculateRow(row));
    });

    row.querySelector('.remove-row').addEventListener('click', () => {
      row.remove();
      calculateTotals();
    });

    const ingredientInput = row.querySelector('.ingredient-name');
    const suggestionBox = row.querySelector('.suggestions');

    ingredientInput.addEventListener('input', async (e) => {
      const text = e.target.value.trim();
      suggestionBox.innerHTML = '';
      suggestionBox.classList.remove('open');
      if (text.length < 3) return;

      const resp = await fetch(`/api/ingredients?query=${encodeURIComponent(text)}`);
      const results = await resp.json();

      if (results.length) {
        suggestionBox.classList.add('open');
      }

      results.forEach((item) => {
        const div = document.createElement('div');
        div.className = 'suggestion-item';
        div.textContent = `${item.name} (${item.ap_quantity} ${item.ap_unit}, ${item.ap_price_display})`;
        div.addEventListener('click', () => {
          ingredientInput.value = item.name;
          row.querySelector('.ap-quantity').value = item.ap_quantity;
          row.querySelector('.ap-unit').value = item.ap_unit;
          row.querySelector('.ap-price').value = Number(item.ap_price).toFixed(2);
          suggestionBox.innerHTML = '';
          suggestionBox.classList.remove('open');
          calculateRow(row);
          calculateTotals();
        });
        suggestionBox.appendChild(div);
      });
    });

    document.addEventListener('click', (e) => {
      if (!row.contains(e.target)) {
        suggestionBox.innerHTML = '';
        suggestionBox.classList.remove('open');
      }
    });
  }

  function addRow() {
    const fragment = rowTemplate.content.cloneNode(true);
    const row = fragment.firstElementChild;
    recipeBody.appendChild(row);
    bindRowEvents(row);
    calculateRow(row);
  }

  addRowButton.addEventListener('click', addRow);
  totalButton.addEventListener('click', calculateTotals);
  recipeForm.querySelectorAll('[name="portions"], [name="spice_factor_percent"]').forEach((el) => {
    el.addEventListener('input', calculateTotals);
  });

  addRow();

  ingredientForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = new FormData(ingredientForm);
    const payload = Object.fromEntries(form.entries());

    const resp = await fetch('/api/ingredients', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    const data = await resp.json();
    document.getElementById('ingredient-message').textContent = data.message;
    ingredientForm.reset();
    ingredientForm.querySelector('[name="ap_unit"]').value = 'each';
  });

  recipeForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const recipeName = recipeForm.querySelector('[name="recipe_name"]').value;
    const portions = recipeForm.querySelector('[name="portions"]').value;
    const spiceFactor = recipeForm.querySelector('[name="spice_factor_percent"]').value;

    const items = [...recipeBody.querySelectorAll('tr')].map((row) => ({
      ingredient: row.querySelector('.ingredient-name').value,
      ep_quantity: row.querySelector('.ep-quantity').value,
      ep_unit: row.querySelector('.ep-unit').value,
      yield_percent: row.querySelector('.yield-percent').value,
      ap_quantity: row.querySelector('.ap-quantity').value,
      ap_unit: row.querySelector('.ap-unit').value,
      ap_price: row.querySelector('.ap-price').value,
    }));

    const resp = await fetch('/api/recipes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        recipe_name: recipeName,
        portions,
        spice_factor_percent: spiceFactor,
        items,
      }),
    });

    if (!resp.ok) {
      const text = await resp.text();
      results.textContent = `Unable to save recipe: ${text}`;
      return;
    }

    const data = await resp.json();
    results.innerHTML = `
      Recipe saved.<br>
      Total cost: ${data.total_cost}<br>
      Cost per portion: ${data.cost_per_portion}<br>
      Total with spice factor adjustment: ${data.total_with_spice}
    `;
  });
}

window.addEventListener('DOMContentLoaded', initApp);
