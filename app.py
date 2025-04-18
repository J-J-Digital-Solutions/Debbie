from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
import os
from datetime import datetime
from sqlalchemy.sql.expression import func
from sqlalchemy import Numeric
import stripe
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from werkzeug.utils import secure_filename


app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.root_path, 'database/products.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'ht7r884932t7cr84392tbrc743829tbrv473829btrcv743829bycr478329cnbyr78xm8u'
UPLOAD_FOLDER = os.path.join(app.static_folder, 'imgs', 'product_imgs')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

stripe.api_key = "sk_test_51PuEkj03NN6R2KGdl6yihdeFRc0df3BXF2CHdBbTNQO5eGkqvn5rlp065zP1SXNsGTsYFOnmlg7zEob4fgD3ooZT00hBYbaaVa"

db = SQLAlchemy(app)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    description = db.Column(db.String(300))
    category = db.Column(db.String(50))
    subcategory = db.Column(db.String(50))
    image = db.Column(db.String(100))
    price = db.Column(Numeric(10, 2))
    stock = db.Column(db.Integer, default=0)


@app.route("/")
def homepage():
    categories = ['Birthdays', 'Seasonal', 'Event', 'NSFW', 'Custom']
    category_products = {}
    for category in categories:
        products = Product.query.filter_by(category=category).order_by(func.random()).limit(3).all()
        category_products[category] = products
    return render_template("home.html", category_products=category_products)


@app.route("/product/<int:product_id>")
def product(product_id):
    product = Product.query.get_or_404(product_id)
    return render_template("product.html", product=product)


################################## ADDING PRODUCTS ##################################
def add_product(name, description, image, price, stock):
    new_product = Product(
        name=name,
        description=description,
        image=image,
        price=price,
        stock=stock
    )
    db.session.add(new_product)
    db.session.commit()
    print(f"Product '{name}' added successfully.")
################################## ADDING PRODUCTS ##################################

@app.route('/cart')
def view_cart():
    if 'cart' not in session:
        session['cart'] = {}

    cart_items = []
    for product_id, quantity in session['cart'].items():
        product = Product.query.get(int(product_id))
        if product:
            cart_items.append({
                'product': product,
                'quantity': quantity
            })

    total = sum(item['product'].price * item['quantity'] for item in cart_items)
    return render_template('cart.html', cart_items=cart_items, total=total)


@app.route('/cart/add/<int:product_id>', methods=['POST', 'GET'])
def add_to_cart(product_id):
    # Ensure 'cart' exists in session
    if 'cart' not in session:
        session['cart'] = {}

    product = Product.query.get_or_404(product_id)
    product_id_str = str(product.id)

    # Get the quantity from the form; default to 1 if not provided
    quantity = request.form.get('quantity', '1')
    quantity = int(quantity) if quantity.isdigit() else 1

    # If it’s already in the cart, just increment, otherwise set it
    if product_id_str in session['cart']:
        session['cart'][product_id_str] += quantity
    else:
        session['cart'][product_id_str] = quantity

    session.modified = True  # Mark the session as modified so changes persist

    flash(f"Added {product.name} (x{quantity}) to cart!", "success")
    return redirect(url_for('view_cart'))


@app.route('/cart/update', methods=['POST'])
def update_cart():
    if 'cart' not in session:
        session['cart'] = {}

    # Process all quantity fields (e.g., "quantity[42]")
    for field_name in request.form:
        if field_name.startswith("quantity[") and field_name.endswith("]"):
            product_id = field_name[9:-1]  # extract the product id
            try:
                session['cart'][product_id] = int(request.form[field_name])
            except ValueError:
                # Ignore invalid input
                continue

    session.modified = True

    # If this is an AJAX request, return JSON data
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        cart_items = []
        total = 0.0
        for pid, quantity in session['cart'].items():
            product = Product.query.get(int(pid))
            if product:
                subtotal = float(product.price) * quantity
                cart_items.append({
                    'product_id': product.id,
                    'subtotal': subtotal
                })
                total += subtotal
        return jsonify({'cart_items': cart_items, 'total': total})
    else:
        flash("Cart updated!", "success")
        return redirect(url_for('view_cart'))


@app.route('/cart/remove/<int:product_id>', methods=['POST', 'GET'])
def remove_from_cart(product_id):
    product_id_str = str(product_id)
    if 'cart' in session and product_id_str in session['cart']:
        session['cart'].pop(product_id_str)
        session.modified = True
        flash("Item removed from cart.", "info")

    # If AJAX request, send back JSON with updated cart data
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        cart_items = []
        total = 0.0
        for pid, quantity in session.get('cart', {}).items():
            product = Product.query.get(int(pid))
            if product:
                subtotal = float(product.price) * quantity
                cart_items.append({
                    'product_id': product.id,
                    'subtotal': subtotal
                })
                total += subtotal
        return jsonify({'cart_items': cart_items, 'total': total, 'cart_empty': total == 0})
    else:
        return redirect(url_for('view_cart'))


@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    try:
        if 'cart' not in session or not session['cart']:
            flash("Your cart is empty!", "error")
            return redirect(url_for('view_cart'))

        # Check stock availability for each item in the cart
        for product_id, quantity in session['cart'].items():
            product = Product.query.get_or_404(product_id)
            if quantity > product.stock:
                flash(
                    f"Not enough stock for {product.name}. Available: {product.stock}, Requested: {quantity}.",
                    "error"
                )
                return redirect(url_for('view_cart'))

        line_items = []
        for product_id, quantity in session['cart'].items():
            product = Product.query.get_or_404(product_id)
            line_items.append({
                'price_data': {
                    'currency': 'gbp',
                    'unit_amount': int(product.price * 100),
                    'product_data': {
                        'name': product.name,
                        'description': product.description,
                        'metadata': {'product_id': str(product.id)}
                    },
                },
                'quantity': quantity,
            })

        # Add delivery fee (without metadata)
        delivery_fee_pence = 399
        line_items.append({
            'price_data': {
                'currency': 'gbp',
                'unit_amount': delivery_fee_pence,
                'product_data': {
                    'name': 'Delivery Fee',
                    'description': 'Flat delivery fee'
                },
            },
            'quantity': 1,
        })

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=line_items,
            mode='payment',
            success_url='http://192.168.0.56:81/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url='http://192.168.0.56:81',
            billing_address_collection='required',
            shipping_address_collection={'allowed_countries': ['GB']}
        )

        return redirect(checkout_session.url, code=303)

    except Exception as e:
        return str(e), 500


@app.route('/buy_now/<int:product_id>', methods=['POST'])
def buy_now(product_id):
    try:
        product = Product.query.get_or_404(product_id)
        quantity = int(request.form.get('quantity', '1'))

        # Check if the desired quantity exceeds available stock
        if quantity > product.stock:
            flash(
                f"Not enough stock for {product.name}. Available: {product.stock}, Requested: {quantity}.",
                "error"
            )
            return redirect(url_for('product', product_id=product.id))

        line_items = [{
            'price_data': {
                'currency': 'gbp',
                'unit_amount': int(product.price * 100),
                'product_data': {
                    'name': product.name,
                    'description': product.description,
                    'metadata': {'product_id': str(product.id)}
                },
            },
            'quantity': quantity,
        }]

        # Add delivery fee (without metadata)
        delivery_fee_pence = 399
        line_items.append({
            'price_data': {
                'currency': 'gbp',
                'unit_amount': delivery_fee_pence,
                'product_data': {
                    'name': 'Delivery Fee',
                    'description': 'Flat delivery fee'
                },
            },
            'quantity': 1,
        })

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=line_items,
            mode='payment',
            success_url='http://192.168.0.56:81/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url='http://192.168.0.56:81',
            billing_address_collection='required',
            shipping_address_collection={'allowed_countries': ['GB']}
        )

        return redirect(checkout_session.url, code=303)

    except Exception as e:
        return str(e), 500


@app.route('/webhook', methods=['POST'])
def stripe_webhook():
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature')
    endpoint_secret = 'whsec_zJTsChvuQhfIoqlxCMUk5b62MH32lK8u'

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except ValueError:
        return 'Invalid payload', 400
    except stripe.error.SignatureVerificationError:
        return 'Invalid signature', 400

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        print(f"Payment for session {session['id']} was successful.")

    return 'Success', 200


@app.route('/success')
def success():
    session_id = request.args.get('session_id')
    if not session_id:
        return "Invalid session.", 400

    # Retrieve the Stripe session
    stripe_session = stripe.checkout.Session.retrieve(session_id)
    if not stripe_session or stripe_session.payment_status != 'paid':
        return "Payment not verified.", 400

    # Retrieve line items and expand the product object to access its metadata
    line_items = stripe.checkout.Session.list_line_items(
        session_id,
        expand=['data.price.product']
    )

    # Deduct stock based on metadata in each line item (skip items without metadata, e.g. delivery fee)
    for item in line_items.data:
        if not item.price.product or not item.price.product.metadata:
            continue
        product_id = item.price.product.metadata.get('product_id')
        if product_id:
            quantity = item.quantity
            product = Product.query.get(int(product_id))
            if product:
                product.stock = max(0, product.stock - quantity)
    db.session.commit()

    # Retrieve customer details from Stripe
    customer_name = stripe_session.customer_details.name or "Unknown Customer"
    customer_email = stripe_session.customer_details.email or "No Email Provided"
    address_obj = stripe_session.customer_details.address
    customer_address = address_obj.line1 if address_obj and address_obj.line1 else "No Address Provided"
    customer_city = address_obj.city if address_obj and address_obj.city else "N/A"
    customer_postal_code = address_obj.postal_code if address_obj and address_obj.postal_code else "N/A"
    customer_country = address_obj.country if address_obj and address_obj.country else "N/A"

    # Build the order summary
    order_summary = ""
    for item in line_items.data:
        product_name = item.description
        quantity = item.quantity
        amount = item.amount_total / 100.0
        order_summary += f" - {product_name} (x{quantity}): £{amount:.2f}\n"

    email_subject = "New Order Received!"
    email_body = (
        f"{email_subject}\n\n"
        f"Order Details:\n"
        f"{order_summary}\n"
        f"Customer Information:\n"
        f" - Name: {customer_name}\n"
        f" - Email: {customer_email}\n"
        f" - Address: {customer_address}\n"
        f" - City: {customer_city}\n"
        f" - Postal Code: {customer_postal_code}\n"
        f" - Country: {customer_country}\n\n"
        f"Please process this order."
    )

    # Send order confirmation email
    smtp_server = 'smtp.gmail.com'
    smtp_port = 465
    sender_email = 'james.robinson156.156@gmail.com'
    sender_password = 'avjv mwqg rorn jgvq'
    receiver_email = 'james.robinson156.156@gmail.com'

    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = receiver_email
    msg['Subject'] = email_subject
    msg.attach(MIMEText(email_body, 'plain'))

    try:
        server = smtplib.SMTP_SSL(smtp_server, smtp_port)
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, receiver_email, msg.as_string())
        server.quit()
    except Exception as e:
        print(f'Failed to send email: {e}')

    # Clear the cart
    session['cart'] = {}
    session.modified = True

    return redirect("/?success=true", code=302)


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        admin_password = request.form.get('admin_password')
        if admin_password == 'Password123':
            session['is_admin'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Incorrect admin password', 'error')
    return render_template('admin/admin_login.html')


@app.route('/admin/dashboard')
def admin_dashboard():
    if 'is_admin' not in session:
        return redirect(url_for('admin_login'))
    products = Product.query.all()
    return render_template('admin/admin_dashboard.html', products=products)


@app.route('/admin/product/new', methods=['GET', 'POST'])
def admin_new_product():
    if 'is_admin' not in session:
        return redirect(url_for('admin_login'))
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        category = request.form.get("category")
        subcategory = request.form.get("subcategory")
        image_file = request.files.get('image')

        if image_file and image_file.filename:
            filename = secure_filename(image_file.filename)
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            image_file.save(save_path)
            image_path = f"imgs/product_imgs/{filename}"
        else:
            image_path = None 

        price_str = request.form.get('price', '0.0')
        price = float(price_str) if price_str else 0.0

        stock_str = request.form.get('stock', '0')
        try:
            stock = int(stock_str)
        except ValueError:
            stock = 0

        new_product = Product(
            name=name,
            description=description,
            category=category,
            subcategory=subcategory,
            image=image_path,
            price=price,
            stock=stock
        )
        db.session.add(new_product)
        db.session.commit()
        return redirect(url_for('admin_dashboard'))

    return render_template('admin/admin_edit_product.html', product=None)


@app.route('/admin/product/<int:product_id>/edit', methods=['GET', 'POST'])
def admin_edit_product(product_id):
    if 'is_admin' not in session:
        return redirect(url_for('admin_login'))

    product = Product.query.get_or_404(product_id)

    if request.method == 'POST':
        product.name = request.form.get('name')
        product.description = request.form.get('description')
        product.category = request.form.get('category')
        product.subcategory = request.form.get('subcategory')

        image_file = request.files.get('image')
        if image_file and image_file.filename.strip():
            filename = secure_filename(image_file.filename)
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            image_file.save(save_path)
            product.image = f"imgs/product_imgs/{filename}"

        price_str = request.form.get('price', '0.0')
        product.price = float(price_str) if price_str else 0.0

        stock_str = request.form.get('stock', '0')
        try:
            product.stock = int(stock_str)
        except ValueError:
            product.stock = 0

        db.session.commit()
        return redirect(url_for('admin_dashboard'))

    return render_template('admin/admin_edit_product.html', product=product)


@app.route('/admin/product/<int:product_id>/delete', methods=['POST'])
def admin_delete_product(product_id):
    if 'is_admin' not in session:
        return redirect(url_for('admin_login'))
    product = Product.query.get_or_404(product_id)
    db.session.delete(product)
    db.session.commit()
    return redirect(url_for('admin_dashboard'))


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=81)