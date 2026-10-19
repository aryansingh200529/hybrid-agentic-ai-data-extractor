import os
import re
import time
import pandas as pd
from urllib.parse import urljoin
from dotenv import load_dotenv
from google import genai
from pydantic import BaseModel, Field
from playwright.sync_api import sync_playwright
from rich.console import Console
from rich.panel import Panel

# 1. Setup Terminal & Secret Key
console = Console()
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY or "Yahan_Apni" in API_KEY:
    console.print("[bold red]❌ Error: Please set your valid GEMINI_API_KEY in the .env file![/bold red]")
    exit()

client = genai.Client(api_key=API_KEY)

# 2. Structure: Define schema for data extraction via AI
class CompanyInfo(BaseModel):
    company_name: str = Field(description="Official name of the company")
    main_business: str = Field(description="1-2 lines explaining what the company does / main products or services")
    email_id: str = Field(description="Official contact email ID if found, else 'Not Found'")
    phone_number: str = Field(description="Contact phone number if found, else 'Not Found'")
    address: str = Field(description="Company headquarters or office address if found, else 'Not Found'")

# 3. Function: Open live Google Chrome and scan website along with 5 inner pages
def scrape_website_live(page, base_url):
    combined_text = ""
    emails_found = set()
    phones_found = set()

    try:
        console.print(f"   [cyan]🌐 Opening in Google Chrome:[/cyan] {base_url}")
        page.goto(base_url, timeout=25000, wait_until="domcontentloaded")
        time.sleep(1.5)

        console.print("   [dim]🖱️  Auto-scrolling Chrome page to scan content...[/dim]")
        for _ in range(3):
            page.mouse.wheel(0, 700)
            time.sleep(0.5)

        body_text = page.locator("body").inner_text()
        html_content = page.content()
        combined_text += f"\n--- HOME PAGE ---\n{body_text[:4000]}"
        emails_found.update(re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", html_content))

        # Extract links and prioritize Contact/Support pages
        links = page.locator("a").all()
        high_priority_urls = []
        normal_sub_urls = []

        for link in links:
            try:
                href = link.get_attribute("href")
                if not href:
                    continue

                # Directly capture hidden emails or phones behind buttons/links
                if href.startswith("mailto:"):
                    emails_found.add(href.replace("mailto:", "").split("?")[0].strip())
                    continue
                if href.startswith("tel:"):
                    phones_found.add(href.replace("tel:", "").strip())
                    continue

                href_lower = href.lower()
                full_url = urljoin(base_url, href)

                if full_url.startswith("http") and full_url != base_url:
                    # Give high priority to Contact, Location, and Support pages
                    if any(w in href_lower for w in ["contact", "support", "reach", "location", "office", "connect", "help"]):
                        if full_url not in high_priority_urls:
                            high_priority_urls.append(full_url)
                    # Give secondary priority to About and Company pages
                    elif any(w in href_lower for w in ["about", "company", "who-we-are", "overview"]):
                        if full_url not in normal_sub_urls and full_url not in high_priority_urls:
                            normal_sub_urls.append(full_url)
            except:
                continue

        # Combine lists and scan top 5 pages
        sub_urls = high_priority_urls + normal_sub_urls
        max_pages = 5

        for sub_url in sub_urls[:max_pages]:
            try:
                console.print(f"   [cyan]🔎 Navigating to inner page:[/cyan] {sub_url}")
                page.goto(sub_url, timeout=15000, wait_until="domcontentloaded")
                time.sleep(1)
                page.mouse.wheel(0, 800)
                time.sleep(0.6)

                sub_text = page.locator("body").inner_text()
                sub_html = page.content()
                combined_text += f"\n--- SUB PAGE ({sub_url}) ---\n{sub_text[:3000]}"
                emails_found.update(re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", sub_html))
            except:
                pass

        if emails_found:
            clean_emails = [
                e for e in emails_found 
                if not e.lower().endswith(('.png', '.jpg', '.jpeg', '.svg', '.webp', '.gif', '.css', '.js'))
            ]
            if clean_emails:
                combined_text += f"\n--- DETECTED EMAILS ---\n{', '.join(clean_emails[:8])}"

        if phones_found:
            combined_text += f"\n--- DETECTED PHONES ---\n{', '.join(list(phones_found)[:5])}"

        return combined_text

    except Exception as e:
        console.print(f"   [red]⚠️ Page load warning: {e}[/red]")
        return combined_text

# 4. Function: Extract exact details using Gemini AI
def extract_with_ai(url, raw_text):
    prompt = f"""
    You are an expert Data Extraction Agent. Analyze the following text scraped from multiple pages of the website ({url}).
    Extract the Company Name, Main Business (what they do), Official Email ID, Phone Number, and Office Address.
    Look carefully across all SUB PAGES and DETECTED EMAILS/PHONES sections.
    If an exact email/address is not explicitly in the text, infer the headquarters city/country if mentioned, or write 'Not Publicly Listed'.
    
    Website Text:
    {raw_text[:15000]}
    """
    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_schema": CompanyInfo,
            "temperature": 0.1,
        },
    )
    return response.parsed

# 5. Main Execution
def main():
    console.print(Panel.fit("[bold cyan]🤖 Live Google Chrome AI Data Extraction Agent[/bold cyan]", border_style="cyan"))

    if not os.path.exists("websites.txt"):
        console.print("[bold red]❌ 'websites.txt' file not found![/bold red]")
        return

    with open("websites.txt", "r") as f:
        urls = [line.strip() for line in f if line.strip()]

    console.print(f"[yellow]📂 Total Websites in Queue: {len(urls)}[/yellow]\n")
    extracted_results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome", 
            headless=False, 
            args=["--start-maximized"]
        )
        page = browser.new_page(no_viewport=True)

        for idx, url in enumerate(urls, start=1):
            if not url.startswith("http"):
                url = "https://" + url

            console.rule(f"[bold yellow]Website {idx} of {len(urls)}: {url}[/bold yellow]")
            raw_text = scrape_website_live(page, url)

            with console.status("[bold magenta]🧠 Gemini AI extracting Company Details...", spinner="dots"):
                try:
                    data = extract_with_ai(url, raw_text)
                    extracted_results.append({
                        "Website URL": url,
                        "Company Name": data.company_name,
                        "Main Business": data.main_business,
                        "Email ID": data.email_id,
                        "Phone Number": data.phone_number,
                        "Address": data.address
                    })

                    card_text = (
                        f"[bold cyan]🏢 Company Name:[/bold cyan] {data.company_name}\n"
                        f"[bold green]💼 Main Business:[/bold green] {data.main_business}\n"
                        f"[bold yellow]📧 Email ID:[/bold yellow]      {data.email_id}\n"
                        f"[bold magenta]📞 Phone:[/bold magenta]         {data.phone_number}\n"
                        f"[bold white]📍 Address:[/bold white]       {data.address}"
                    )
                    console.print(Panel(card_text, title=f"✅ Extracted Data ({idx}/{len(urls)})", border_style="green"))

                except Exception as e:
                    console.print(f"   [bold red]✖ AI Error on {url}: {e}[/bold red]\n")

        browser.close()

    # Save to Excel safely (No PermissionError Crash!)
    if extracted_results:
        output_file = "Extracted_Company_Data.xlsx"
        df = pd.DataFrame(extracted_results)
        
        try:
            df.to_excel(output_file, index=False)
            console.print(f"\n[bold green]🎉 ALL DONE! All data saved to '{output_file}'. Opening Excel...[/bold green]")
            os.startfile(output_file)
        except PermissionError:
            backup_file = f"Extracted_Company_Data_{int(time.time())}.xlsx"
            df.to_excel(backup_file, index=False)
            console.print(f"\n[bold yellow]⚠️ Warning: Previous Excel file was open, so saved new data to '{backup_file}'![/bold yellow]")
            os.startfile(backup_file)

if __name__ == "__main__":
    main()
