import json
import os
import sqlite3
from datetime import datetime
from functools import wraps
from urllib.parse import quote

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash


# إعداد التطبيق بشكل بسيط وواضح للمبتدئين.
app = Flask(__name__)
app.secret_key = "change-this-secret-key-for-production"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "database.db")

# عدل هذه القيم عند إطلاق المتجر الحقيقي.
STORE_NAME = "STORM FIT"
WHATSAPP_NUMBER = "9647891040488"
META_PIXEL_ID = "YOUR_PIXEL_ID"


def get_db_connection():
    """فتح اتصال مع قاعدة بيانات SQLite."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def column_exists(conn, table_name, column_name):
    """فحص وجود عمود قبل إضافته، حتى لا يتعطل التطبيق عند التشغيل المتكرر."""
    columns = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(column["name"] == column_name for column in columns)


def create_tables():
    """إنشاء الجداول والحقول الأساسية للمتجر."""
    conn = get_db_connection()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user'
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            image TEXT NOT NULL,
            description TEXT NOT NULL
        )
        """
    )

    # إضافة حقول جديدة بدون حذف بياناتك القديمة.
    extra_product_columns = {
        "category": "TEXT NOT NULL DEFAULT 'تيشيرتات'",
        "sizes": "TEXT NOT NULL DEFAULT 'S,M,L,XL'",
        "featured": "INTEGER NOT NULL DEFAULT 1",
    }
    for column_name, column_sql in extra_product_columns.items():
        if not column_exists(conn, "products", column_name):
            conn.execute(f"ALTER TABLE products ADD COLUMN {column_name} {column_sql}")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            city TEXT NOT NULL,
            address TEXT NOT NULL,
            notes TEXT,
            items TEXT NOT NULL,
            total REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'جديد',
            created_at TEXT NOT NULL
        )
        """
    )

    # حسابات إدارة جاهزة للتجربة.
    admin_accounts = [
        ("admin", "admin123"),
        ("مدير", "123456"),
    ]
    for username, password in admin_accounts:
        admin = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if admin is None:
            conn.execute(
                "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                (username, generate_password_hash(password), "admin"),
            )

    starter_products = [
        (
            1,
            "شورت رياضي أسود",
            35000,
            "images/linen-shirt.png",
            "شورت خفيف ومريح للتمارين، الجيم، والمشاوير اليومية.",
            "شورتات",
            "S,M,L,XL",
            1,
        ),
        (
            2,
            "تيشيرت رياضي أحمر",
            30000,
            "images/تيشيرت أحمر.png",
            "تيشيرت سريع التنسيق بإحساس رياضي مناسب للشارع والتمرين.",
            "تيشيرتات",
            "S,M,L,XL,XXL",
            1,
        ),
        (
            3,
            "تيشيرت أسود بريميوم",
            32000,
            "images/تيشيرت أسود.png",
            "تيشيرت أسود بتصميم نظيف وخامة مناسبة للاستخدام اليومي.",
            "تيشيرتات",
            "S,M,L,XL,XXL",
            1,
        ),
        (
            4,
            "هودي أسود رياضي",
            55000,
            "images/هودي أسود.png",
            "هودي عملي ودافئ بإطلالة ستريت وير تناسب الشتاء والتمارين الخفيفة.",
            "هوديز",
            "M,L,XL,XXL",
            1,
        ),
    ]

    # إذا كانت المنتجات الأربعة موجودة من النسخة القديمة، نحدثها بدل تكرارها.
    for product in starter_products:
        conn.execute(
            """
            INSERT INTO products (id, name, price, image, description, category, sizes, featured)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                price = excluded.price,
                image = excluded.image,
                description = excluded.description,
                category = excluded.category,
                sizes = excluded.sizes,
                featured = excluded.featured
            """,
            product,
        )

    conn.commit()
    conn.close()


def admin_required(view_function):
    """حماية صفحات الإدارة."""
    @wraps(view_function)
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            flash("يجب تسجيل الدخول كمدير للوصول إلى هذه الصفحة.")
            return redirect(url_for("login"))
        return view_function(*args, **kwargs)

    return wrapper


def product_image_path(image):
    """إرجاع رابط الصورة سواء كانت محلية أو رابطا كاملا."""
    if image.startswith("http://") or image.startswith("https://"):
        return image
    return url_for("static", filename=image)


def format_price(price):
    """تنسيق السعر بالدينار العراقي."""
    return f"{int(price):,} د.ع"


def get_cart():
    """إرجاع السلة من الجلسة."""
    return session.setdefault("cart", {})


def get_cart_items():
    """تحويل بيانات السلة إلى منتجات مفهومة للقوالب."""
    cart = session.get("cart", {})
    if not cart:
        return [], 0

    conn = get_db_connection()
    items = []
    total = 0

    for key, quantity in cart.items():
        product_id, size = key.split(":")
        product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if product is None:
            continue

        item_total = product["price"] * quantity
        total += item_total
        items.append(
            {
                "key": key,
                "product": product,
                "size": size,
                "quantity": quantity,
                "total": item_total,
            }
        )

    conn.close()
    return items, total


def cart_count():
    return sum(session.get("cart", {}).values())


def create_whatsapp_link(order=None, items=None, total=0):
    """إنشاء رابط واتساب جاهز للطلب."""
    lines = [f"مرحبا، أريد الطلب من {STORE_NAME}:"]

    if items:
        for item in items:
            product = item["product"]
            lines.append(
                f"- {product['name']} | المقاس: {item['size']} | الكمية: {item['quantity']} | {format_price(item['total'])}"
            )

    lines.append(f"المجموع: {format_price(total)}")

    if order:
        lines.extend(
            [
                "",
                f"الاسم: {order['customer_name']}",
                f"الهاتف: {order['phone']}",
                f"المدينة: {order['city']}",
                f"العنوان: {order['address']}",
            ]
        )

    return f"https://wa.me/{WHATSAPP_NUMBER}?text={quote(chr(10).join(lines))}"


app.jinja_env.globals.update(
    product_image_path=product_image_path,
    format_price=format_price,
    cart_count=cart_count,
    store_name=STORE_NAME,
    meta_pixel_id=META_PIXEL_ID,
)


@app.route("/")
def index():
    """الصفحة الرئيسية للبراند."""
    conn = get_db_connection()
    featured_products = conn.execute(
        "SELECT * FROM products WHERE featured = 1 ORDER BY id DESC LIMIT 4"
    ).fetchall()
    latest_products = conn.execute("SELECT * FROM products ORDER BY id DESC LIMIT 4").fetchall()
    conn.close()
    return render_template(
        "index.html",
        featured_products=featured_products,
        latest_products=latest_products,
    )


@app.route("/products")
def products():
    """صفحة المنتجات مع فلترة بسيطة."""
    selected_category = request.args.get("category", "الكل")
    selected_size = request.args.get("size", "الكل")

    conn = get_db_connection()
    all_products = conn.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
    categories = [
        row["category"]
        for row in conn.execute("SELECT DISTINCT category FROM products ORDER BY category").fetchall()
    ]
    conn.close()

    filtered_products = []
    for product in all_products:
        category_matches = selected_category == "الكل" or product["category"] == selected_category
        size_matches = selected_size == "الكل" or selected_size in product["sizes"].split(",")
        if category_matches and size_matches:
            filtered_products.append(product)

    return render_template(
        "products.html",
        products=filtered_products,
        categories=categories,
        selected_category=selected_category,
        selected_size=selected_size,
        sizes=["S", "M", "L", "XL", "XXL"],
    )


@app.route("/product/<int:product_id>")
def product_details(product_id):
    """صفحة تفاصيل المنتج."""
    conn = get_db_connection()
    product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    conn.close()

    if product is None:
        flash("المنتج غير موجود.")
        return redirect(url_for("products"))

    return render_template("product_details.html", product=product)


@app.route("/cart/add/<int:product_id>", methods=("POST",))
def add_to_cart(product_id):
    """إضافة منتج للسلة."""
    size = request.form.get("size", "").strip()
    quantity = int(request.form.get("quantity", 1))

    conn = get_db_connection()
    product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    conn.close()

    if product is None:
        flash("المنتج غير موجود.")
        return redirect(url_for("products"))

    available_sizes = product["sizes"].split(",")
    if size not in available_sizes:
        flash("اختر مقاسا متاحا قبل إضافة المنتج للسلة.")
        return redirect(url_for("product_details", product_id=product_id))

    cart = get_cart()
    key = f"{product_id}:{size}"
    cart[key] = cart.get(key, 0) + max(quantity, 1)
    session["cart"] = cart
    session.modified = True

    flash("تمت إضافة المنتج إلى السلة.")
    return redirect(url_for("cart"))


@app.route("/cart")
def cart():
    """عرض السلة."""
    items, total = get_cart_items()
    whatsapp_link = create_whatsapp_link(items=items, total=total)
    return render_template("cart.html", items=items, total=total, whatsapp_link=whatsapp_link)


@app.route("/cart/update", methods=("POST",))
def update_cart():
    """تحديث الكمية أو حذف عنصر من السلة."""
    key = request.form["key"]
    action = request.form["action"]
    cart = get_cart()

    if key in cart:
        if action == "remove":
            cart.pop(key)
        else:
            quantity = int(request.form.get("quantity", 1))
            cart[key] = max(quantity, 1)

    session["cart"] = cart
    session.modified = True
    return redirect(url_for("cart"))


@app.route("/checkout", methods=("GET", "POST"))
def checkout():
    """إتمام الطلب وحفظه في لوحة الإدارة."""
    items, total = get_cart_items()
    if not items:
        flash("السلة فارغة.")
        return redirect(url_for("products"))

    if request.method == "POST":
        customer_name = request.form["customer_name"].strip()
        phone = request.form["phone"].strip()
        city = request.form["city"].strip()
        address = request.form["address"].strip()
        notes = request.form.get("notes", "").strip()

        if not customer_name or not phone or not city or not address:
            flash("يرجى تعبئة معلومات الطلب الأساسية.")
            return redirect(url_for("checkout"))

        order_items = [
            {
                "product_id": item["product"]["id"],
                "name": item["product"]["name"],
                "size": item["size"],
                "quantity": item["quantity"],
                "price": item["product"]["price"],
                "total": item["total"],
            }
            for item in items
        ]

        conn = get_db_connection()
        cursor = conn.execute(
            """
            INSERT INTO orders (customer_name, phone, city, address, notes, items, total, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                customer_name,
                phone,
                city,
                address,
                notes,
                json.dumps(order_items, ensure_ascii=False),
                total,
                datetime.now().strftime("%Y-%m-%d %H:%M"),
            ),
        )
        conn.commit()
        order_id = cursor.lastrowid
        order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        conn.close()

        session["cart"] = {}
        session.modified = True
        whatsapp_link = create_whatsapp_link(order=order, items=items, total=total)
        return render_template("order_success.html", order=order, whatsapp_link=whatsapp_link)

    return render_template("checkout.html", items=items, total=total)


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/contact")
def contact():
    direct_whatsapp = create_whatsapp_link(total=0)
    return render_template("contact.html", whatsapp_link=direct_whatsapp)


@app.route("/register", methods=("GET", "POST"))
def register():
    """إنشاء حساب مستخدم."""
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]

        if not username or not password:
            flash("اسم المستخدم وكلمة المرور مطلوبان.")
            return redirect(url_for("register"))

        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                (username, generate_password_hash(password), "user"),
            )
            conn.commit()
            flash("تم إنشاء الحساب بنجاح. يمكنك تسجيل الدخول الآن.")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("اسم المستخدم مستخدم بالفعل.")
        finally:
            conn.close()

    return render_template("register.html")


@app.route("/login", methods=("GET", "POST"))
def login():
    """تسجيل دخول المستخدمين والمدير."""
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]

        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()

        if user and check_password_hash(user["password"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            flash(f"أهلا بعودتك، {user['username']}!")

            if user["role"] == "admin":
                return redirect(url_for("admin"))
            return redirect(url_for("index"))

        flash("اسم المستخدم أو كلمة المرور غير صحيحة.")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("تم تسجيل الخروج بنجاح.")
    return redirect(url_for("index"))


@app.route("/admin")
@admin_required
def admin():
    """لوحة الإدارة الرئيسية."""
    conn = get_db_connection()
    products_count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    orders_count = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    latest_orders = conn.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 5").fetchall()
    conn.close()
    return render_template(
        "admin.html",
        products_count=products_count,
        orders_count=orders_count,
        latest_orders=latest_orders,
    )


@app.route("/admin/products")
@admin_required
def admin_products():
    conn = get_db_connection()
    products = conn.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("admin_products.html", products=products)


@app.route("/admin/add", methods=("GET", "POST"))
@admin_required
def add_product():
    """إضافة منتج جديد."""
    if request.method == "POST":
        name = request.form["name"].strip()
        price = request.form["price"]
        image = request.form["image"].strip()
        category = request.form["category"].strip()
        sizes = request.form["sizes"].strip()
        description = request.form["description"].strip()
        featured = 1 if request.form.get("featured") else 0

        if not name or not price or not image or not category or not sizes or not description:
            flash("جميع الحقول مطلوبة.")
            return redirect(url_for("add_product"))

        conn = get_db_connection()
        conn.execute(
            """
            INSERT INTO products (name, price, image, description, category, sizes, featured)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (name, price, image, description, category, sizes, featured),
        )
        conn.commit()
        conn.close()

        flash("تمت إضافة المنتج بنجاح.")
        return redirect(url_for("admin_products"))

    return render_template("add_product.html")


@app.route("/admin/edit/<int:product_id>", methods=("GET", "POST"))
@admin_required
def edit_product(product_id):
    """تعديل منتج."""
    conn = get_db_connection()
    product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()

    if product is None:
        conn.close()
        flash("المنتج غير موجود.")
        return redirect(url_for("admin_products"))

    if request.method == "POST":
        name = request.form["name"].strip()
        price = request.form["price"]
        image = request.form["image"].strip()
        category = request.form["category"].strip()
        sizes = request.form["sizes"].strip()
        description = request.form["description"].strip()
        featured = 1 if request.form.get("featured") else 0

        if not name or not price or not image or not category or not sizes or not description:
            flash("جميع الحقول مطلوبة.")
            conn.close()
            return redirect(url_for("edit_product", product_id=product_id))

        conn.execute(
            """
            UPDATE products
            SET name = ?, price = ?, image = ?, description = ?, category = ?, sizes = ?, featured = ?
            WHERE id = ?
            """,
            (name, price, image, description, category, sizes, featured, product_id),
        )
        conn.commit()
        conn.close()

        flash("تم تحديث المنتج بنجاح.")
        return redirect(url_for("admin_products"))

    conn.close()
    return render_template("edit_product.html", product=product)


@app.route("/admin/delete/<int:product_id>", methods=("POST",))
@admin_required
def delete_product(product_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()

    flash("تم حذف المنتج بنجاح.")
    return redirect(url_for("admin_products"))


@app.route("/admin/orders")
@admin_required
def admin_orders():
    conn = get_db_connection()
    orders = conn.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("admin_orders.html", orders=orders, json=json)


@app.route("/admin/orders/<int:order_id>/status", methods=("POST",))
@admin_required
def update_order_status(order_id):
    status = request.form["status"]
    conn = get_db_connection()
    conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    conn.commit()
    conn.close()
    flash("تم تحديث حالة الطلب.")
    return redirect(url_for("admin_orders"))


if __name__ == "__main__":
    create_tables()
    app.run(debug=True, use_reloader=False)
