import asyncio
from playwright.async_api import async_playwright
import time

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        base = 'http://127.0.0.1:5000'
        await page.goto(base)

        # Register unique user
        ts = int(time.time())
        email = f'playwright_user_{ts}@example.com'
        await page.click('button.auth-tab:nth-child(2)')
        await page.fill('#regName', 'Playwright Tester')
        await page.fill('#regEmail', email)
        await page.fill('#regPassword', 'Aa1!strong')
        await page.fill('#regConfirmPassword', 'Aa1!strong')
        await page.fill('#regPhone', '0712345678')
        await page.click('button.btn-primary:has-text("Register")')

        # Wait then switch to login
        await page.wait_for_timeout(800)
        await page.click('button.auth-tab:nth-child(1)')
        await page.fill('#loginEmail', email)
        await page.fill('#loginPassword', 'Aa1!strong')
        await page.click('button.btn-primary:has-text("Login")')

        # Wait for dashboard
        await page.wait_for_selector('#availableBalance')
        before = await page.inner_text('#availableBalance')
        print('before balance:', before)

        # Go to Tasks and click Complete Survey
        await page.click('a[href="#tasks"]')
        await page.wait_for_selector('#tasksContainer')
        # Find the survey button (task 2)
        await page.click('#task-2')

        # Survey page should open
        await page.wait_for_selector('#q1')
        await page.select_option('#q1', 'friend')
        await page.select_option('#q2', '5')
        await page.select_option('#q3', 'daily')
        await page.select_option('#q4', 'yes')
        await page.fill('#q5', 'Looks good')
        await page.click('button.btn-primary:has-text("Submit Survey")')

        # Wait for update and check dashboard balance
        await page.wait_for_timeout(1000)
        await page.click('a[href="#dashboard"]')
        await page.wait_for_selector('#availableBalance')
        after = await page.inner_text('#availableBalance')
        print('after balance:', after)

        await browser.close()

if __name__ == '__main__':
    asyncio.run(run())
