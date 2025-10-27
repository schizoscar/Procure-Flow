// static/js/main.js
document.addEventListener('DOMContentLoaded', function () {
    // Hamburger menu toggle
    const hamburger = document.getElementById('hamburger');
    const sidebar = document.getElementById('sidebar');
    const mainContent = document.getElementById('mainContent');

    if (hamburger && sidebar) {
        hamburger.addEventListener('click', function () {
            sidebar.classList.toggle('active');
        });
    }

    // Close sidebar when clicking outside on mobile
    document.addEventListener('click', function (event) {
        if (window.innerWidth <= 768 && sidebar.classList.contains('active')) {
            if (!sidebar.contains(event.target) && !hamburger.contains(event.target)) {
                sidebar.classList.remove('active');
            }
        }
    });

    // Form validation
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function (e) {
            const requiredFields = form.querySelectorAll('[required]');
            let valid = true;

            requiredFields.forEach(field => {
                if (!field.value.trim()) {
                    valid = false;
                    field.style.borderColor = 'var(--error)';
                } else {
                    field.style.borderColor = '';
                }
            });

            if (!valid) {
                e.preventDefault();
                showAlert('Please fill in all required fields', 'error');
            }
        });
    });

    // Show alert function
    window.showAlert = function (message, type = 'info') {
        const alertDiv = document.createElement('div');
        alertDiv.className = `alert alert-${type}`;
        alertDiv.textContent = message;

        const firstCard = document.querySelector('.card');
        if (firstCard) {
            firstCard.parentNode.insertBefore(alertDiv, firstCard);
        } else {
            document.querySelector('.main-content').prepend(alertDiv);
        }

        setTimeout(() => {
            alertDiv.remove();
        }, 5000);
    };

    // Dynamic item addition for PR form
    const addItemBtn = document.getElementById('addItem');
    const itemsContainer = document.getElementById('itemsContainer');

    if (addItemBtn && itemsContainer) {
        addItemBtn.addEventListener('click', function () {
            const itemIndex = itemsContainer.children.length;
            const itemHTML = `
                <div class="card mb-2 item-row">
                    <div class="d-flex justify-between align-center">
                        <h4>Item ${itemIndex + 1}</h4>
                        <button type="button" class="btn btn-danger remove-item" onclick="this.parentElement.parentElement.remove()">
                            Remove
                        </button>
                    </div>
                    <div class="grid-2">
                        <div class="form-group">
                            <label class="form-label required">Item Name</label>
                            <input type="text" class="form-control" name="items[${itemIndex}][item_name]" required>
                        </div>
                        <div class="form-group">
                            <label class="form-label required">Quantity</label>
                            <input type="number" class="form-control" name="items[${itemIndex}][quantity]" min="1" required>
                        </div>
                        <div class="form-group">
                            <label class="form-label">Specification</label>
                            <input type="text" class="form-control" name="items[${itemIndex}][specification]">
                        </div>
                        <div class="form-group">
                            <label class="form-label">Brand</label>
                            <input type="text" class="form-control" name="items[${itemIndex}][brand]">
                        </div>
                        <div class="form-group">
                            <label class="form-label">Balance Stock</label>
                            <input type="number" class="form-control" name="items[${itemIndex}][balance_stock]" min="0">
                        </div>
                        <div class="form-group">
                            <label class="form-label required">Item Category</label>
                            <select class="form-control form-select" name="items[${itemIndex}][item_category]" required>
                                <option value="">Select Category</option>
                                <!-- Categories will be populated by server -->
                            </select>
                        </div>
                    </div>
                </div>
            `;
            itemsContainer.insertAdjacentHTML('beforeend', itemHTML);
        });
    }

    // Supplier selection checkboxes
    const selectAllBtn = document.getElementById('selectAll');
    const supplierCheckboxes = document.querySelectorAll('.supplier-checkbox');

    if (selectAllBtn) {
        selectAllBtn.addEventListener('click', function () {
            const isChecked = this.dataset.checked !== 'true';
            supplierCheckboxes.forEach(checkbox => {
                checkbox.checked = isChecked;
            });
            this.dataset.checked = isChecked;
            this.textContent = isChecked ? 'Deselect All' : 'Select All';
        });
    }
});

// Form validation functions
function validateEmail(email) {
    const pattern = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
    return pattern.test(email);
}

function validatePhone(phone) {
    const pattern = /^(\+?6?01)[0-46-9]-*[0-9]{7,8}$/;
    return pattern.test(phone.replace(/[\s-]/g, ''));
}

function validatePassword(password) {
    return password.length >= 6 &&
        /[a-zA-Z]/.test(password) &&
        /\d/.test(password);
}
