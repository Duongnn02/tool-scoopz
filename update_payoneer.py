import re

with open('xnowtrader_pro.html', 'r', encoding='utf-8') as f:
    text = f.read()

print("Original VI Title:")
m1 = re.search(r'sBannerTitle:\s*".*?"', text[text.rfind('vi:'):])
if m1: print(m1.group(0))

print("Original VI Desc:")
m2 = re.search(r'sBannerDesc:\s*".*?"', text[text.rfind('vi:'):])
if m2: print(m2.group(0))

# 1. Update the Hero paragraph
old_hero = r"Scoopz is a fast-growing short video platform dedicated to\s*showcasing real, storyworthy videos\. Our mission is to bring authentic stories\s*to life, capturing genuine moments that resonate with our community\."
new_hero = "XnowTrader LLC is a digital media company focused on content creation and creator operations. We produce and publish original short-form video content and monetize through creator platforms and brand collaborations."
text = re.sub(old_hero, new_hero, text)

# 2. Update Powered by Scoopz to Monetized via Scoopz in English
text = text.replace('sBannerTitle">Powered by Scoopz', 'sBannerTitle">Monetized via Scoopz')
text = text.replace('sBannerTitle: "Powered by Scoopz"', 'sBannerTitle: "Monetized via Scoopz"')

# 3. Update the description for Scoopz banner
# First the HTML one
old_banner_desc = r'Our core growth\s*and monetization strategy relies on Scoopz, leveraging its algorithm to\s*deliver unparalleled reach and native revenue streams\.'
new_banner_desc = 'We publish content on Scoopz and generate revenue through platform monetization programs and promotional collaborations.'
text = re.sub(old_banner_desc, new_banner_desc, text)

# Then the JS one
text = re.sub(r'sBannerDesc:\s*"Our core growth[^"]+"', 'sBannerDesc: "We publish content on Scoopz and generate revenue through platform monetization programs and promotional collaborations."', text)

# Update VI Strings
if m1:
    text = text.replace(m1.group(0), 'sBannerTitle: "Kiếm tiền qua Scoopz"')
if m2:
    text = text.replace(m2.group(0), 'sBannerDesc: "Chúng tôi xuất bản nội dung trên Scoopz và tạo doanh thu thông qua các chương trình kiếm tiền của nền tảng và hợp tác quảng cáo."')

with open('xnowtrader_pro.html', 'w', encoding='utf-8') as f:
    f.write(text)

print("Updated successfully!")
