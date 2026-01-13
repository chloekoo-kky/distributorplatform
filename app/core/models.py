# distributorplatform/app/core/models.py
import os
from io import BytesIO
from PIL import Image
from django.db import models
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import InMemoryUploadedFile, TemporaryUploadedFile

class SiteSetting(models.Model):
    site_name = models.CharField(
        max_length=100,
        default="Distributor Platform",
        help_text="The name of your site. Use '|' to split into two lines (e.g., 'English Name | Chinese Name')."
    )
    site_logo = models.ImageField(
        upload_to='site_branding/',
        blank=True,
        null=True,
        help_text="Upload a logo to display next to the site name in the navigation bar."
    )
    customer_service_whatsapp = models.CharField(
        max_length=20,
        default="60199333030",
        help_text="Format: 60123456789 (No '+' or dashes). Agent orders will be sent here."
    )
    site_name_color = models.CharField(
        max_length=7,
        default='#4F46E5', # Indigo-600
        help_text="Color for the main site name text."
    )
    site_name_subtitle_color = models.CharField(
        max_length=7,
        default='#818CF8', # Indigo-400
        help_text="Color for the site name subtitle (second line)."
    )
    nav_background_color = models.CharField(
        max_length=7,
        default='#FFFFFF',
        help_text="Hex color code for the top navigation bar (e.g., #FFFFFF)."
    )

    # --- NEW: Checkout Page Settings ---
    checkout_title = models.CharField(max_length=200, default="Checkout Confirmation|结账确认", help_text="Use '|' to separate lines.")
    checkout_empty_msg = models.CharField(max_length=200, default="Your checkout session is empty or expired.|您的结账会话为空或已过期。", help_text="Use '|' to separate lines.")
    checkout_return_btn = models.CharField(max_length=100, default="Return to Order Page|返回订单页面", help_text="Use '|' to separate lines.")

    checkout_summary_title = models.CharField(max_length=200, default="Order Summary|订单摘要", help_text="Use '|' to separate lines.")
    checkout_col_product = models.CharField(max_length=100, default="Product|产品", help_text="Use '|' to separate lines.")
    checkout_col_qty = models.CharField(max_length=100, default="Qty|数量", help_text="Use '|' to separate lines.")
    checkout_col_price = models.CharField(max_length=100, default="Unit Price|单价", help_text="Use '|' to separate lines.")
    checkout_col_total = models.CharField(max_length=100, default="Total|总计", help_text="Use '|' to separate lines.")

    checkout_total_label = models.CharField(max_length=100, default="Total:|总计：", help_text="Use '|' to separate lines.")
    checkout_commission_label = models.CharField(max_length=100, default="Estimated Commission:|预计佣金：", help_text="Use '|' to separate lines.")

    checkout_back_btn = models.CharField(max_length=100, default="Back to Cart|返回购物车", help_text="Use '|' to separate lines.")
    checkout_confirm_btn = models.CharField(max_length=100, default="Confirm Order|确认订单", help_text="Use '|' to separate lines.")

    # --- Payment Settings (Existing) ---
    payment_enabled = models.BooleanField(
        default=False,
        help_text="Enable or disable online payments globally."
    )
    payment_provider = models.CharField(
        max_length=20,
        choices=[
            ('SENANGPAY', 'SenangPay (FPX/Credit Card)'),
            ('BILLPLZ', 'Billplz (FPX/Malaysia)'),
            ('STRIPE', 'Stripe (Credit Card)'),
        ],
        default='SENANGPAY',
        help_text="Select the logic handler for processing payments."
    )
    payment_gateway_url = models.CharField(
        max_length=255,
        default="https://dev.toyyibpay.com/index.php/api/createBill",
        help_text="The API Endpoint URL (e.g., https://toyyibpay.com/index.php/api/createBill)."
    )
    payment_api_key = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Secret Key / API Key",
        help_text="Your Secret Key (SenangPay) or API Key."
    )
    payment_category_code = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Merchant ID / Collection ID",
        help_text="Required: Merchant ID (SenangPay) or Collection ID (Billplz)."
    )
    market_insights_nav_text = models.CharField(
        max_length=100,
        default="市场热报 | Market Insights",
        help_text="Label for the 'Market Insights' link in the main navigation."
    )
    news_section_title = models.CharField(
        max_length=100,
        default="最近更新 | Latest News",
        help_text="Title for the News section."
    )
    faq_section_title = models.CharField(
        max_length=100,
        default="Frequently Asked Questions",
        help_text="Title for the FAQ section."
    )
    market_insights_title = models.CharField(
        max_length=100,
        default="市场热报 | Market Insights",
        help_text="Title for the Sidebar Insights widget."
    )
    announcements_title = models.CharField(
        max_length=100,
        default="布告栏 | Announcements",
        help_text="Title for the Announcements widget."
    )
    sidebar_search_title = models.CharField(
        max_length=100,
        default="搜索产品 | Search Products",
        help_text="Title for the Search widget in the sidebar."
    )
    sidebar_search_placeholder = models.CharField(
        max_length=100,
        default="关键字搜索... | Search by keyword...",
        help_text="Placeholder text for the sidebar search input."
    )
    sidebar_search_button_text = models.CharField(
        max_length=50,
        default="搜索 | Search",
        help_text="Label for the sidebar search button."
    )
    sidebar_news_title = models.CharField(
        max_length=100,
        default="最新消息 | Latest News",
        help_text="Title for the News widget in the sidebar (Product List/Detail pages)."
    )
    footer_col2_title = models.CharField(
        max_length=100,
        default="主要链接 | Quick Links",
        help_text="Title for the second column in the footer."
    )
    footer_col3_title = models.CharField(
        max_length=100,
        default="產品分類 | Product Categories",
        help_text="Title for the third column (Categories) in the footer."
    )

    footer_col4_title = models.CharField(
        max_length=100,
        default="联系我們 | Contact Us",
        help_text="Title for the fourth column (Contact Info) in the footer."
    )

    # Standard Link Labels
    footer_link_home_text = models.CharField(
        max_length=100,
        default="主页 | Home",
        help_text="Label for the 'Home' link in the footer."
    )
    footer_link_products_text = models.CharField(
        max_length=100,
        default="所有产品 | All Products",
        help_text="Label for the 'All Products' link in the footer."
    )
    footer_link_blog_text = models.CharField(
        max_length=100,
        default="市场热报 | Market Insights",
        help_text="Label for the 'Market Insights' link in the footer."
    )
    footer_link_account_text = models.CharField(
        max_length=100,
        default="我的账户 | My Account",
        help_text="Label for the 'My Account' link in the footer."
    )
    mobile_nav_products_text = models.CharField(
        max_length=50,
        default="产品 | Products",
        help_text="Label for 'Products' in mobile bottom nav."
    )
    mobile_nav_order_text = models.CharField(
        max_length=50,
        default="下单 | Order",
        help_text="Label for 'Order' in mobile bottom nav."
    )
    mobile_nav_account_text = models.CharField(
        max_length=50,
        default="账户 | Account",
        help_text="Label for 'Account' in mobile bottom nav."
    )
    mobile_nav_login_text = models.CharField(
        max_length=50,
        default="登录 | Login",
        help_text="Label for 'Login' in mobile bottom nav."
    )
    user_menu_signed_in_text = models.CharField(
        max_length=100,
        default="登录为 | Signed in as",
        help_text="Label for 'Signed in as' in the user dropdown."
    )
    user_menu_profile_text = models.CharField(
        max_length=100,
        default="订单记录 | Order History",
        help_text="Label for the link pointing to the Order History page (formerly Profile)."
    )
    user_menu_settings_text = models.CharField(
        max_length=100,
        default="个人资料 | Profile",
        help_text="Label for the link pointing to User Profile settings."
    )
    user_menu_signout_text = models.CharField(
        max_length=100,
        default="退出 | Sign out",
        help_text="Label for 'Sign out' button in the user dropdown."
    )
    place_order_title = models.CharField(
        max_length=100,
        default="建立新订单 | Place a New Order",
        help_text="Main title on the Place Order page."
    )
    place_order_search_placeholder = models.CharField(
        max_length=100,
        default="按名称 or SKU 搜索... | Search products by name or SKU...",
        help_text="Placeholder text for the search bar."
    )
    featured_products_title = models.CharField(
        max_length=100,
        default="必看产品 | Featured Products",
        help_text="Title for the Featured Products section on the homepage."
    )
    special_promotions_title = models.CharField(
        max_length=100,
        default="特别优惠 | Special Promotions",
        help_text="Title for the Promotions section on the product list page."
    )
    special_promotions_subtitle = models.CharField(
        max_length=255,
        default="限时独家优惠。 | Exclusive deals available for a limited time.",
        help_text="Subtitle/Description under the Promotions title."
    )
    product_action_enquire_text = models.CharField(
        max_length=50,
        default="询问 | Enquire",
        help_text="Label for the 'Enquire' button (WhatsApp)."
    )
    product_action_share_text = models.CharField(
        max_length=50,
        default=" 分享| Share",
        help_text="Label for the 'Share' button."
    )
    product_action_details_text = models.CharField(
        max_length=50,
        default="详情 | Details",
        help_text="Label for the 'Details' button (Quick View modal)."
    )
    price_on_request_text = models.CharField(
        max_length=100,
        default="价格面议 | Price available upon request.",
        help_text="Label displayed when a product has no price set."
    )
    view_details_text = models.CharField(
        max_length=50,
        default="查看详情 | View Details",
        help_text="Label for 'View Details' links (e.g., in promotions)."
    )
    login_required_text = models.CharField(
        max_length=50,
        default="需要登录 | Login required",
        help_text="Label displayed when user must login to view price."
    )
    homepage_view_all_text = models.CharField(
        max_length=50,
        default="查看全部 | View All",
        help_text="Label for 'View All' links on the homepage category sections."
    )
    place_order_add_text = models.CharField(
        max_length=50,
        default="加入购物车 | Add to Cart",
        help_text="Label for the 'Add' button in the order table."
    )
    place_order_added_text = models.CharField(
        max_length=50,
        default="已加入购物车 | Added",
        help_text="Label for the 'Added' button state in the order table."
    )
    place_order_empty_cart_text = models.CharField(
        max_length=100,
        default="您的购物车是空的。 | Your cart is empty.",
        help_text="Message displayed when the cart is empty in the order summary."
    )
    profile_hello_text = models.CharField(
        max_length=50,
        default="你好 | Hello",
        help_text="Greeting text before the username."
    )
    profile_signout_text = models.CharField(
        max_length=50,
        default="退出 | Sign Out",
        help_text="Label for the Sign Out button."
    )

    # Agent Dashboard
    agent_dashboard_title = models.CharField(
        max_length=100,
        default="代理仪表板 | Agent Dashboard",
        help_text="Title for the Agent Dashboard section."
    )
    agent_stats_earnings_text = models.CharField(
        max_length=100,
        default="总收入 (累计) | Total Earnings (All Time)",
        help_text="Label for the Total Earnings stat card."
    )
    agent_stats_pending_text = models.CharField(
        max_length=100,
        default="待付金额 | Pending Payout",
        help_text="Label for the Pending Payout stat card."
    )
    agent_stats_paid_text = models.CharField(
        max_length=100,
        default="已付金额 | Paid Out",
        help_text="Label for the Paid Out stat card."
    )

    # Section Headers
    commission_history_title = models.CharField(
        max_length=100,
        default="佣金记录 | Commission History",
        help_text="Title for the Commission History table."
    )
    order_history_title = models.CharField(
        max_length=100,
        default="Order History | 订单记录",
        help_text="Title for the Order History table."
    )
    nav_login_text = models.CharField(
        max_length=50,
        default="Login | 登录",
        help_text="Label for the 'Login' link in the top navigation."
    )
    nav_register_text = models.CharField(
        max_length=50,
        default="Register | 注册",
        help_text="Label for the 'Register' button in the top navigation."
    )
    login_title = models.CharField(
        max_length=100,
        default="Sign In | 登录",
        help_text="Browser tab title for the login page."
    )
    login_heading = models.CharField(
        max_length=100,
        default="Sign in to your account | 登录您的账户",
        help_text="Main heading on the login card."
    )
    login_register_text = models.CharField(
        max_length=100,
        default="Or register for a new account | 或注册新账户",
        help_text="Link text to the registration page."
    )
    login_username_placeholder = models.CharField(
        max_length=50,
        default="Username | 用户名",
        help_text="Placeholder for the username input."
    )
    login_password_placeholder = models.CharField(
        max_length=50,
        default="Password | 密码",
        help_text="Placeholder for the password input."
    )
    login_btn_text = models.CharField(
        max_length=50,
        default="Sign In | 登录",
        help_text="Label for the Sign In button."
    )
    login_error_text = models.CharField(
        max_length=200,
        default="Your username and password didn't match. Please try again. | 用户名或密码不匹配，请重试。",
        help_text="Error message displayed when login fails."
    )
    register_title = models.CharField(
        max_length=100,
        default="Join Us | 注册",
        help_text="Browser tab title for the register page."
    )
    register_heading = models.CharField(
        max_length=100,
        default="Create your account | 创建您的账户",
        help_text="Main heading on the register card."
    )
    register_username_placeholder = models.CharField(
        max_length=50,
        default="Username | 用户名",
        help_text="Placeholder for the username input."
    )
    register_email_placeholder = models.CharField(
        max_length=50,
        default="Email | 电子邮件",
        help_text="Placeholder for the email input."
    )
    register_phone_placeholder = models.CharField(
        max_length=50,
        default="Phone Number | 电话号码",
        help_text="Placeholder for the phone number input."
    )
    register_password_placeholder = models.CharField(
        max_length=50,
        default="Password | 密码",
        help_text="Placeholder for the password input."
    )
    register_btn_text = models.CharField(
        max_length=50,
        default="Register | 注册",
        help_text="Label for the Register button."
    )
    register_signin_text = models.CharField(
        max_length=100,
        default="Already have an account? Sign in | 已有账户？登录",
        help_text="Link text to redirect to the login page."
    )

    # --- NEW: Verification Modal Labels ---
    verify_modal_title = models.CharField(
        max_length=100,
        default="验证邮件账号 | Verify your email",
        help_text="Title for the OTP verification modal."
    )
    verify_btn_text = models.CharField(
        max_length=50,
        default="验证账户 | Verify Account",
        help_text="Label for the Verify button."
    )

    subscription_title = models.CharField(
        max_length=100,
        default="Choose the right plan for you | 选择适合您的计划",
        help_text="Title for the Subscription Plans page."
    )
    subscription_subtitle = models.CharField(
        max_length=255,
        default="Unlock higher commissions and exclusive features by upgrading your agent status. | 升级代理身份，解锁更高佣金和专属功能。",
        help_text="Subtitle for the Subscription Plans page."
    )
    # Table Headers
    place_order_header_product = models.CharField(max_length=50, default="产品 | Product")
    place_order_header_sku = models.CharField(max_length=50, default="SKU")
    place_order_header_price = models.CharField(max_length=50, default="售价 | Selling Price")
    place_order_header_profit = models.CharField(max_length=50, default="您的利润 | Your Profit")

    # Sidebar / Summary
    place_order_summary_title = models.CharField(max_length=100, default="Order Summary | 订单摘要")
    place_order_total_label = models.CharField(max_length=50, default="Total Price: | 总价:")
    place_order_est_profit_label = models.CharField(max_length=50, default="Estimated Profit: | 预计利润:")
    place_order_btn_label = models.CharField(max_length=50, default="Place Order | 下单")

    settings_page_title = models.CharField(max_length=100, default="Account Settings | 账户设置", help_text="Main title for the Settings page.")
    settings_profile_title = models.CharField(max_length=100, default="Profile Information | 个人资料", help_text="Header for the Profile section.")
    settings_security_title = models.CharField(max_length=100, default="Security | 安全设置", help_text="Header for the Security section.")
    settings_security_desc = models.CharField(max_length=255, default="Update your password to keep your account secure. | 更新您的密码以保持账户安全。", help_text="Description under Security header.")

    # Form Labels
    settings_label_first_name = models.CharField(max_length=50, default="First Name | 名", help_text="Label for First Name.")
    settings_label_last_name = models.CharField(max_length=50, default="Last Name | 姓", help_text="Label for Last Name.")
    settings_label_email = models.CharField(max_length=50, default="Email Address | 电子邮件", help_text="Label for Email.")
    settings_label_phone = models.CharField(max_length=50, default="Phone Number | 电话号码", help_text="Label for Phone.")
    settings_label_address = models.CharField(max_length=50, default="Shipping Address | 收货地址", help_text="Label for Address.")

    # Password Labels
    settings_label_current_pwd = models.CharField(max_length=50, default="Current Password | 当前密码", help_text="Label for Current Password.")
    settings_label_new_pwd = models.CharField(max_length=50, default="New Password | 新密码", help_text="Label for New Password.")
    settings_label_confirm_pwd = models.CharField(max_length=50, default="Confirm New Password | 确认新密码", help_text="Label for Confirm Password.")

    # Buttons
    settings_btn_edit = models.CharField(max_length=50, default="Edit | 编辑", help_text="Button text for Edit.")
    settings_btn_cancel = models.CharField(max_length=50, default="Cancel | 取消", help_text="Button text for Cancel.")
    settings_btn_save = models.CharField(max_length=50, default="Save Changes | 保存更改", help_text="Button text for Save.")
    settings_btn_change_pwd = models.CharField(max_length=50, default="Change Password | 更改密码", help_text="Button text for Change Password.")

    # --- Category Header Styling ---
    category_header_background_color = models.CharField(
        max_length=7,
        default='#C7D2FE', # Indigo-200
        help_text="Background color for the category header."
    )
    category_header_border_color = models.CharField(
        max_length=7,
        default='#C7D2FE',
        help_text="Border color for the category header."
    )
    category_header_title_color = models.CharField(
        max_length=7,
        default='#3730A3', # Indigo-800
        help_text="Text color for the category main title."
    )
    category_header_subtitle_color = models.CharField(
        max_length=7,
        default='#4F46E5', # Indigo-600
        help_text="Text color for the category subtitle."
    )
    section_header_background_color = models.CharField(
        max_length=7,
        default='#E0E7FF', # Indigo-100
        help_text="Background color for extra content section headers."
    )
    section_header_border_color = models.CharField(
        max_length=7,
        default='#E0E7FF', # Indigo-100
        help_text="Border color for extra content section headers."
    )
    section_header_title_color = models.CharField(
        max_length=7,
        default='#3730A3', # Indigo-800
        help_text="Text color for extra content section headers."
    )


    # Contact Info
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=50, blank=True)
    contact_address = models.TextField(blank=True, help_text="Physical address displayed in footer.")

    # Footer Content
    footer_about_text = models.TextField(
        blank=True,
        help_text="A short paragraph about your company displayed in the footer."
    )

    # Social Media
    facebook_url = models.URLField(blank=True, verbose_name="Facebook URL")
    instagram_url = models.URLField(blank=True, verbose_name="Instagram URL")
    twitter_url = models.URLField(blank=True, verbose_name="Twitter/X URL")
    linkedin_url = models.URLField(blank=True, verbose_name="LinkedIn URL")

    def _get_lines(self, text):
        """Helper to split text by pipe '|' symbol."""
        if text and '|' in text:
            return [line.strip() for line in text.split('|')]
        return [text] if text else []

    @property
    def site_name_lines(self):
        return self._get_lines(self.site_name)

    @property
    def market_insights_nav_lines(self):
        return self._get_lines(self.market_insights_nav_text)

    @property
    def news_title_lines(self):
        return self._get_lines(self.news_section_title)

    @property
    def faq_title_lines(self):
        return self._get_lines(self.faq_section_title)

    @property
    def market_insights_title_lines(self):
        return self._get_lines(self.market_insights_title)

    @property
    def announcements_title_lines(self):
        return self._get_lines(self.announcements_title)

    @property
    def sidebar_search_title_lines(self):
        return self._get_lines(self.sidebar_search_title)

    @property
    def sidebar_search_placeholder_lines(self):
        return self._get_lines(self.sidebar_search_placeholder)

    @property
    def sidebar_search_button_lines(self):
        return self._get_lines(self.sidebar_search_button_text)

    @property
    def sidebar_news_title_lines(self):
        return self._get_lines(self.sidebar_news_title)

    @property
    def footer_col2_title_lines(self):
        return self._get_lines(self.footer_col2_title)

    @property
    def footer_link_home_lines(self):
        return self._get_lines(self.footer_link_home_text)

    @property
    def footer_link_products_lines(self):
        return self._get_lines(self.footer_link_products_text)

    @property
    def footer_link_blog_lines(self):
        return self._get_lines(self.footer_link_blog_text)

    @property
    def footer_link_account_lines(self):
        return self._get_lines(self.footer_link_account_text)

    @property
    def footer_col3_title_lines(self):
        return self._get_lines(self.footer_col3_title)

    @property
    def footer_col4_title_lines(self):
        return self._get_lines(self.footer_col4_title)

    @property
    def mobile_nav_products_lines(self):
        return self._get_lines(self.mobile_nav_products_text)

    @property
    def mobile_nav_order_lines(self):
        return self._get_lines(self.mobile_nav_order_text)

    @property
    def mobile_nav_account_lines(self):
        return self._get_lines(self.mobile_nav_account_text)

    @property
    def mobile_nav_login_lines(self):
        return self._get_lines(self.mobile_nav_login_text)

    @property
    def user_menu_signed_in_lines(self):
        return self._get_lines(self.user_menu_signed_in_text)

    @property
    def user_menu_profile_lines(self):
        return self._get_lines(self.user_menu_profile_text)

    @property
    def user_menu_settings_lines(self):
        return self._get_lines(self.user_menu_settings_text)

    @property
    def user_menu_signout_lines(self):
        return self._get_lines(self.user_menu_signout_text)

    @property
    def place_order_title_lines(self): return self._get_lines(self.place_order_title)

    @property
    def place_order_search_lines(self): return self._get_lines(self.place_order_search_placeholder)

    @property
    def place_order_header_product_lines(self): return self._get_lines(self.place_order_header_product)

    @property
    def place_order_header_sku_lines(self): return self._get_lines(self.place_order_header_sku)

    @property
    def place_order_header_price_lines(self): return self._get_lines(self.place_order_header_price)

    @property
    def place_order_header_profit_lines(self): return self._get_lines(self.place_order_header_profit)

    @property
    def place_order_summary_title_lines(self): return self._get_lines(self.place_order_summary_title)

    @property
    def place_order_total_lines(self): return self._get_lines(self.place_order_total_label)

    @property
    def place_order_est_profit_lines(self): return self._get_lines(self.place_order_est_profit_label)

    @property
    def place_order_btn_lines(self): return self._get_lines(self.place_order_btn_label)

    @property
    def featured_products_title_lines(self):
        return self._get_lines(self.featured_products_title)

    @property
    def special_promotions_title_lines(self):
        return self._get_lines(self.special_promotions_title)

    @property
    def special_promotions_subtitle_lines(self):
        return self._get_lines(self.special_promotions_subtitle)

    @property
    def product_action_enquire_lines(self):
        return self._get_lines(self.product_action_enquire_text)

    @property
    def product_action_share_lines(self):
        return self._get_lines(self.product_action_share_text)

    @property
    def product_action_details_lines(self):
        return self._get_lines(self.product_action_details_text)

    @property
    def price_on_request_lines(self):
        return self._get_lines(self.price_on_request_text)

    @property
    def view_details_lines(self):
        return self._get_lines(self.view_details_text)

    @property
    def login_required_lines(self):
        return self._get_lines(self.login_required_text)

    @property
    def homepage_view_all_lines(self):
        return self._get_lines(self.homepage_view_all_text)

    @property
    def place_order_add_lines(self):
        return self._get_lines(self.place_order_add_text)

    @property
    def place_order_added_lines(self):
        return self._get_lines(self.place_order_added_text)

    @property
    def place_order_empty_cart_lines(self):
        return self._get_lines(self.place_order_empty_cart_text)

    @property
    def checkout_title_lines(self): return self._get_lines(self.checkout_title)
    @property
    def checkout_empty_msg_lines(self): return self._get_lines(self.checkout_empty_msg)
    @property
    def checkout_return_btn_lines(self): return self._get_lines(self.checkout_return_btn)
    @property
    def checkout_summary_title_lines(self): return self._get_lines(self.checkout_summary_title)
    @property
    def checkout_col_product_lines(self): return self._get_lines(self.checkout_col_product)
    @property
    def checkout_col_qty_lines(self): return self._get_lines(self.checkout_col_qty)
    @property
    def checkout_col_price_lines(self): return self._get_lines(self.checkout_col_price)
    @property
    def checkout_col_total_lines(self): return self._get_lines(self.checkout_col_total)
    @property
    def checkout_total_label_lines(self): return self._get_lines(self.checkout_total_label)
    @property
    def checkout_commission_label_lines(self): return self._get_lines(self.checkout_commission_label)
    @property
    def checkout_back_btn_lines(self): return self._get_lines(self.checkout_back_btn)
    @property
    def checkout_confirm_btn_lines(self): return self._get_lines(self.checkout_confirm_btn)

    @property
    def profile_hello_lines(self): return self._get_lines(self.profile_hello_text)

    @property
    def profile_signout_lines(self): return self._get_lines(self.profile_signout_text)

    @property
    def agent_dashboard_title_lines(self): return self._get_lines(self.agent_dashboard_title)

    @property
    def agent_stats_earnings_lines(self): return self._get_lines(self.agent_stats_earnings_text)

    @property
    def agent_stats_pending_lines(self): return self._get_lines(self.agent_stats_pending_text)

    @property
    def agent_stats_paid_lines(self): return self._get_lines(self.agent_stats_paid_text)

    @property
    def commission_history_title_lines(self): return self._get_lines(self.commission_history_title)

    @property
    def order_history_title_lines(self): return self._get_lines(self.order_history_title)

    @property
    def nav_login_lines(self):
        return self._get_lines(self.nav_login_text)

    @property
    def nav_register_lines(self):
        return self._get_lines(self.nav_register_text)

    @property
    def login_title_lines(self): return self._get_lines(self.login_title)

    @property
    def login_heading_lines(self): return self._get_lines(self.login_heading)

    @property
    def login_register_lines(self): return self._get_lines(self.login_register_text)

    @property
    def login_username_lines(self): return self._get_lines(self.login_username_placeholder)

    @property
    def login_password_lines(self): return self._get_lines(self.login_password_placeholder)

    @property
    def login_btn_lines(self): return self._get_lines(self.login_btn_text)

    @property
    def login_error_lines(self): return self._get_lines(self.login_error_text)

    @property
    def register_title_lines(self): return self._get_lines(self.register_title)

    @property
    def register_heading_lines(self): return self._get_lines(self.register_heading)

    @property
    def register_username_lines(self): return self._get_lines(self.register_username_placeholder)

    @property
    def register_email_lines(self): return self._get_lines(self.register_email_placeholder)

    @property
    def register_phone_lines(self): return self._get_lines(self.register_phone_placeholder)

    @property
    def register_password_lines(self): return self._get_lines(self.register_password_placeholder)

    @property
    def register_btn_lines(self): return self._get_lines(self.register_btn_text)

    @property
    def register_signin_lines(self): return self._get_lines(self.register_signin_text)

    @property
    def verify_modal_title_lines(self): return self._get_lines(self.verify_modal_title)

    @property
    def verify_btn_lines(self): return self._get_lines(self.verify_btn_text)

    @property
    def subscription_title_lines(self):
        return self._get_lines(self.subscription_title)

    @property
    def subscription_subtitle_lines(self):
        return self._get_lines(self.subscription_subtitle)

    @property
    def settings_page_title_lines(self): return self._get_lines(self.settings_page_title)

    @property
    def settings_profile_title_lines(self): return self._get_lines(self.settings_profile_title)

    @property
    def settings_security_title_lines(self): return self._get_lines(self.settings_security_title)

    @property
    def settings_security_desc_lines(self): return self._get_lines(self.settings_security_desc)

    @property
    def settings_label_first_name_lines(self): return self._get_lines(self.settings_label_first_name)

    @property
    def settings_label_last_name_lines(self): return self._get_lines(self.settings_label_last_name)

    @property
    def settings_label_email_lines(self): return self._get_lines(self.settings_label_email)

    @property
    def settings_label_phone_lines(self): return self._get_lines(self.settings_label_phone)

    @property
    def settings_label_address_lines(self): return self._get_lines(self.settings_label_address)

    @property
    def settings_label_current_pwd_lines(self): return self._get_lines(self.settings_label_current_pwd)

    @property
    def settings_label_new_pwd_lines(self): return self._get_lines(self.settings_label_new_pwd)

    @property
    def settings_label_confirm_pwd_lines(self): return self._get_lines(self.settings_label_confirm_pwd)

    @property
    def settings_btn_edit_lines(self): return self._get_lines(self.settings_btn_edit)

    @property
    def settings_btn_cancel_lines(self): return self._get_lines(self.settings_btn_cancel)

    @property
    def settings_btn_save_lines(self): return self._get_lines(self.settings_btn_save)

    @property
    def settings_btn_change_pwd_lines(self): return self._get_lines(self.settings_btn_change_pwd)

    @classmethod
    def load(cls):
        """
        Singleton pattern helper: always returns the first instance,
        or creates one if it doesn't exist.
        """
        if cls.objects.exists():
            return cls.objects.first()
        return cls.objects.create()

    def save(self, *args, **kwargs):
        # Ensure only one instance exists (Singleton pattern)
        if not self.pk and SiteSetting.objects.exists():
            # If you try to create a new one, it updates the existing one instead
            existing = SiteSetting.objects.first()
            return existing
        return super(SiteSetting, self).save(*args, **kwargs)

    def __str__(self):
        return "Site Configuration"

    class Meta:
        verbose_name = "Site Configuration"
        verbose_name_plural = "Site Configuration"

class ProductFeature(models.Model):
    title = models.CharField(max_length=50, help_text="Top line (e.g., 'Free Shipping')")
    subtitle = models.CharField(max_length=50, blank=True, help_text="Bottom line (e.g., 'Orders over $100')")
    order = models.PositiveIntegerField(default=0, help_text="Order of display (1-4 recommended)")

    class Meta:
        ordering = ['order']
        verbose_name = "Global Product Feature"

    def __str__(self):
        return self.title

class Banner(models.Model):
    LOCATION_CHOICES = [
        ('HOME_HERO', 'Home Page Hero | 首页横幅'),
        ('HOME_SUB', 'Home Sub-Feature (Side-by-Side) | 首页副横幅'),
        ('GLOBAL_TOP', 'Global Top Banner (Category Nav) | 全局顶部横幅'),
    ]

    POSITION_CHOICES = [
        ('left-top', 'Top Left'),
        ('center-top', 'Top Center'),
        ('right-top', 'Top Right'),
        ('left-middle', 'Middle Left'),
        ('center-middle', 'Middle Center'),
        ('right-middle', 'Middle Right'),
        ('left-bottom', 'Bottom Left'),
        ('center-bottom', 'Bottom Center'),
        ('right-bottom', 'Bottom Right'),
    ]

    location = models.CharField(
        max_length=20,
        choices=LOCATION_CHOICES,
        default='HOME_HERO',
        help_text="Where this banner should appear."
    )
    title = models.CharField(max_length=200, blank=True, help_text="Main heading text.")
    subtitle = models.TextField(blank=True, help_text="Subtitle or description text.")

    background_image = models.ImageField(
        upload_to='banners/',
        blank=True,
        null=True,
        help_text="Background image for the banner."
    )

    # NEW: Background Color Field
    background_color = models.CharField(
        max_length=7,
        default='#312E81',
        help_text="Hex color code (e.g., #312E81) used if no image is provided or as a fallback."
    )

    background_opacity = models.PositiveIntegerField(
        default=90,
        help_text="Opacity percentage (0-100). 0 is transparent, 100 is solid."
    )

    content_position = models.CharField(
        max_length=20,
        choices=POSITION_CHOICES,
        default='center-middle',
        help_text="Position of the text content."
    )

    button_text = models.CharField(max_length=50, blank=True, help_text="Text for the call-to-action button.")
    button_link = models.CharField(max_length=200, blank=True, help_text="URL or path for the button.")

    is_active = models.BooleanField(default=True, help_text="Uncheck to hide this banner.")
    order = models.PositiveIntegerField(default=0, help_text="Order of priority.")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_location_display()} - {self.title}"

    @property
    def rgba_color(self):
        """Returns the CSS rgba() string based on color and opacity."""
        hex_color = self.background_color.lstrip('#')
        try:
            # Convert Hex to RGB
            r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
            # Convert 0-100 opacity to 0.0-1.0
            a = self.background_opacity / 100.0
            return f"rgba({r}, {g}, {b}, {a})"
        except ValueError:
            return self.background_color # Fallback if invalid hex

    class Meta:
        ordering = ['location', 'order', '-created_at']
        verbose_name = "Banner / Hero Image"

    def save(self, *args, **kwargs):
        # Image optimization logic (same as before)
        if self.background_image and isinstance(self.background_image.file, (InMemoryUploadedFile, TemporaryUploadedFile)):
            try:
                img = Image.open(self.background_image)
                if img.mode != 'RGB':
                    img = img.convert('RGB')

                max_width = 1920
                if img.width > max_width:
                    ratio = max_width / float(img.width)
                    new_height = int(float(img.height) * ratio)
                    img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)

                output = BytesIO()
                img.save(output, format='JPEG', quality=85, optimize=True)
                output.seek(0)

                new_name = os.path.splitext(self.background_image.name)[0] + '.jpg'
                self.background_image = ContentFile(output.read(), name=new_name)
            except Exception as e:
                print(f"Error optimizing banner image: {e}")

        super(Banner, self).save(*args, **kwargs)

class ThemeSetting(SiteSetting):
    class Meta:
        proxy = True  # This means it uses the SiteSetting table, no new table created
        verbose_name = "Theme & Color Settings"
        verbose_name_plural = "Theme & Color Settings"

class PaymentSetting(SiteSetting):
    """
    Proxy model to create a separate 'Payment Configuration' menu in Admin.
    """
    class Meta:
        proxy = True
        verbose_name = "Payment Configuration"
        verbose_name_plural = "Payment Configuration"

class PaymentOption(models.Model):
    OPTION_TYPES = [
        ('GATEWAY', 'Online Gateway (Uses Site Config)'),
        ('COD', 'Cash On Delivery'),
        ('MANUAL', 'Manual / Bank Transfer'),
    ]
    name = models.CharField(max_length=100, help_text="Display name (e.g., 'Online Banking', 'COD').")
    option_type = models.CharField(
        max_length=20,
        choices=OPTION_TYPES,
        default='GATEWAY',
        help_text="GATEWAY triggers the active online provider. COD/MANUAL just records the order."
    )
    description = models.TextField(blank=True, help_text="Instructions displayed to the user (e.g. Bank details).")
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.get_option_type_display()})"

    class Meta:
        verbose_name = "Payment Option"
        verbose_name_plural = "Payment Options"
