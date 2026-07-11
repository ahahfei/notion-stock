import os
import sys
import math
from notion_client import Client
import yfinance as yf

# 修正：強制關閉 yfinance 的快取功能，避免 sqlite database is locked 錯誤
yf.set_tz_cache_location(None)

# 1. 初始化 Notion Client
notion_token = os.environ.get("NOTION_TOKEN")
database_id = os.environ.get("DATABASE_ID")

if not notion_token or not database_id:
    print("錯誤：找不到 NOTION_TOKEN 或 DATABASE_ID 環境變數。")
    sys.exit(1)

notion = Client(auth=notion_token)

def get_notion_stocks():
    """從 Notion Database 取得所有股票資料"""
    stocks = []
    has_more = True
    start_cursor = None
    
    while has_more:
        kwargs = {"database_id": database_id}
        if start_cursor:
            kwargs["start_cursor"] = start_cursor
            
        response = notion.databases.query(**kwargs)
        
        for row in response.get("results", []):
            page_id = row["id"]
            properties = row.get("properties", {})
            
            # 取得 Ticker 欄位
            ticker_data = properties.get("Ticker", {})
            ticker_type = ticker_data.get("type")
            
            ticker = ""
            # 同時支援 Rich Text (文字屬性) 與 Title (標題屬性)
            if ticker_type == "rich_text" and ticker_data.get("rich_text"):
                ticker = "".join([t["plain_text"] for t in ticker_data["rich_text"]]).strip()
            elif ticker_type == "title" and ticker_data.get("title"):
                ticker = "".join([t["plain_text"] for t in ticker_data["title"]]).strip()
                
            if ticker:
                stocks.append({"page_id": page_id, "ticker": ticker})
                
        has_more = response.get("has_more", False)
        start_cursor = response.get("next_cursor")
        
    return stocks

def get_stock_prices(tickers):
    """使用 yfinance 批次查詢最新股價"""
    if not tickers:
        return {}
    
    print(f"正在從 Yahoo Finance 查詢股價: {tickers}")
    prices = {}
    try:
        # 加上 nans_to_nulls=False 確保新版 yfinance 下載穩定
        data = yf.download(tickers, period="1d", group_by="ticker", progress=False, nans_to_nulls=False)
        
        for ticker in tickers:
            try:
                if len(tickers) == 1:
                    price = data['Close'].iloc[-1]
                else:
                    price = data[ticker]['Close'].iloc[-1]
                
                if not math.isnan(price):
                    prices[ticker] = round(float(price), 2)
            except Exception as e:
                print(f"無法解析 {ticker} 的股價: {e}")
    except Exception as e:
        print(f"Yahoo Finance 下載失敗: {e}")
        
    return prices

def update_notion_price(page_id, price):
    """更新 Notion 的 Current price 欄位"""
    try:
        notion.pages.update(
            page_id=page_id,
            properties={
                "Current price": {
                    "number": price
                }
            }
        )
        return True
    except Exception as e:
        print(f"更新 Notion 失敗 (Page ID: {page_id}): {e}")
        return False

def main():
    print("開始執行 Notion 股價更新排程...")
    
    # 步驟 1: 抓取 Notion 資料
    stocks = get_notion_stocks()
    if not stocks:
        print("Notion Database 中沒有找到任何 Ticker，請確認欄位名稱是否為 'Ticker' 且有資料。")
        return
        
    print(f"成功從 Notion 讀取到 {len(stocks)} 筆股票資料。")
    
    # 步驟 2: 整理所有的 Ticker 並查詢股價
    ticker_list = list(set([s["ticker"] for s in stocks]))
    prices = get_stock_prices(ticker_list)
    
    # 步驟 3: 回填股價到 Notion
    success_count = 0
    for stock in stocks:
        ticker = stock["ticker"]
        page_id = stock["page_id"]
        
        if ticker in prices:
            price = prices[ticker]
            if update_notion_price(page_id, price):
                print(f"成功更新 {ticker}: ${price}")
                success_count += 1
        else:
            print(f"跳過 {ticker}：未能取得有效股價。")
            
    print(f"執行完畢！成功更新 {success_count} / {len(stocks)} 筆資料。")

if __name__ == "__main__":
    main()
