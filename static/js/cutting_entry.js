/* Fish-cutting entry screen: live pay preview, select-all, style → size filter.
 * The server re-checks and re-prices everything on save; this only helps the supervisor see it first. */
(function () {
    'use strict';

    var form = document.getElementById('cut-entry');
    if (!form) return;

    var prices = JSON.parse(document.getElementById('cut-prices').textContent);
    var text = JSON.parse(document.getElementById('cut-text').textContent);
    var dateInput = form.querySelector('[name="work_date"]');
    var sizeSelect = form.querySelector('[name="item"]');
    var styleRadios = form.querySelectorAll('[name="style"]');
    var selectAll = document.getElementById('cut-select-all');
    var summary = document.getElementById('cut-summary');
    var submitButton = form.querySelector('button[type="submit"]');
    var rows = Array.prototype.slice.call(form.querySelectorAll('.cut-row'));

    // Every size option, kept aside: iOS ignores hidden <option>s, so the list is rebuilt per style.
    var allSizes = Array.prototype.slice.call(sizeSelect.querySelectorAll('option')).map(function (option) {
        return option.cloneNode(true);
    });

    function grouped(number) {
        return Number(number).toLocaleString('en-US');
    }

    function fill(template, values) {
        return template.replace(/\{(\w+)\}/g, function (_, key) { return values[key]; });
    }

    // The rate in force on `isoDate`: the latest one starting on or before it (same rule as the server).
    function rateOn(itemId, isoDate) {
        var item = prices[itemId];
        if (!item || !isoDate) return null;
        var best = null;
        item.rates.forEach(function (rate) {
            if (rate[0] <= isoDate && (best === null || rate[0] > best[0])) best = rate;
        });
        return best === null ? null : best[1];
    }

    function chosenStyle() {
        var checked = form.querySelector('[name="style"]:checked');
        return checked ? checked.value : null;
    }

    function showSizesForStyle() {
        var style = chosenStyle();
        var keep = sizeSelect.value;
        var matching = allSizes.filter(function (option) { return option.dataset.style === style; });
        sizeSelect.innerHTML = '';
        matching.forEach(function (option) { sizeSelect.appendChild(option.cloneNode(true)); });
        if (matching.some(function (option) { return option.value === keep; })) sizeSelect.value = keep;
    }

    function refresh() {
        var day = dateInput.value;
        var count = 0;
        var total = 0;
        rows.forEach(function (row) {
            var include = row.querySelector('.cut-include');
            var boxes = parseInt(row.querySelector('.cut-boxes').value, 10);
            var override = row.querySelector('.cut-override');
            var price = rateOn((override && override.value) || sizeSelect.value, day);
            var priceLabel = row.querySelector('.cut-row-price');
            var totalLabel = row.querySelector('.cut-row-total');

            priceLabel.textContent = price === null ? text.no_rate : fill(text.per_box, {price: grouped(price)});
            priceLabel.classList.toggle('is-missing', price === null);
            row.classList.toggle('is-on', include.checked);

            if (include.checked && boxes > 0 && price !== null) {
                count += 1;
                total += boxes * price;
                totalLabel.textContent = '₩' + grouped(boxes * price);
            } else {
                totalLabel.textContent = '';
            }
        });
        summary.textContent = fill(text.summary, {count: count, total: grouped(total)});
        selectAll.checked = rows.length > 0 && rows.every(function (row) {
            return row.querySelector('.cut-include').checked;
        });
    }

    selectAll.addEventListener('change', function () {
        rows.forEach(function (row) { row.querySelector('.cut-include').checked = selectAll.checked; });
        refresh();
    });

    rows.forEach(function (row) {
        var include = row.querySelector('.cut-include');
        var boxes = row.querySelector('.cut-boxes');
        var override = row.querySelector('.cut-override');
        boxes.addEventListener('input', function () {
            var count = parseInt(boxes.value, 10);
            if (count > 0) include.checked = true;  // a number of boxes means they worked
            else if (boxes.value.trim() === '' || count === 0) include.checked = false;  // blank or 0: they didn't
            refresh();
        });
        include.addEventListener('change', refresh);
        if (override) override.addEventListener('change', refresh);
    });

    Array.prototype.forEach.call(styleRadios, function (radio) {
        radio.addEventListener('change', function () { showSizesForStyle(); refresh(); });
    });
    sizeSelect.addEventListener('change', refresh);
    dateInput.addEventListener('change', refresh);

    // One tap, one save: block a second submit while the first is on its way.
    var sending = false;
    form.addEventListener('submit', function (event) {
        if (sending) { event.preventDefault(); return; }
        sending = true;
        submitButton.disabled = true;
    });
    window.addEventListener('pageshow', function (event) {
        if (event.persisted && sending) {
            // Back to a form that was already sent: open a fresh one rather than reuse it. (The server
            // also refuses to file new rows under a spent form, but a clean form avoids the detour.)
            window.location.replace(window.location.href);
            return;
        }
        sending = false;
        submitButton.disabled = false;
    });

    showSizesForStyle();
    refresh();

    // After a refused save, bring the first row to fix into view: on a phone it is usually
    // far below the "nothing was saved" message.
    var firstError = form.querySelector('.cut-row.has-error, .form-group.has-error');
    if (firstError && firstError.scrollIntoView) firstError.scrollIntoView({block: 'center'});
}());
