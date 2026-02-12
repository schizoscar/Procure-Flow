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

document.addEventListener('DOMContentLoaded', function () {

    const toggleBtn = document.getElementById('toggleAllSuppliers');
    if (!toggleBtn) return;

    toggleBtn.addEventListener('click', function () {

        const checkboxes = document.querySelectorAll('.supplier-checkbox');
        const allChecked = [...checkboxes].every(cb => cb.checked);

        checkboxes.forEach(cb => cb.checked = !allChecked);

        toggleBtn.textContent = allChecked ? 'Select All' : 'Deselect All';
    });

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
