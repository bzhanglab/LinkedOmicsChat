"""
Web search tools for agents using DuckDuckGo
"""
from typing import Optional, List, Dict, Any
import logging
from ddgs import DDGS

logger = logging.getLogger(__name__)


class WebSearchTool:
    """Tool for performing web searches using DuckDuckGo"""

    def __init__(self):
        self.ddgs = DDGS()

    async def search(
        self,
        query: str,
        max_results: int = 5,
        region: str = "wt-wt",
        safesearch: str = "moderate",
        timelimit: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Perform a web search using DuckDuckGo

        Args:
            query: Search query string
            max_results: Maximum number of results to return
            region: Region for search (default: worldwide)
            safesearch: Safe search setting (off, moderate, strict)
            timelimit: Time limit for results (d=day, w=week, m=month, y=year)

        Returns:
            List of search results with title, link, and snippet
        """
        try:
            logger.info(f"Performing web search for: {query} (timelimit: {timelimit})")

            results = []
            search_results = self.ddgs.text(
                query,
                region=region,
                safesearch=safesearch,
                max_results=max_results,
                timelimit=timelimit
            )

            for result in search_results:
                results.append({
                    "title": result.get("title", ""),
                    "link": result.get("href", ""),
                    "snippet": result.get("body", ""),
                })

            logger.info(f"Found {len(results)} search results")
            return results

        except Exception as e:
            logger.error(f"Error performing web search: {e}")
            return []

    async def search_news(
        self,
        query: str,
        max_results: int = 5,
        region: str = "wt-wt"
    ) -> List[Dict[str, Any]]:
        """
        Search for news articles using DuckDuckGo News

        Args:
            query: Search query string
            max_results: Maximum number of results to return
            region: Region for search (default: worldwide)

        Returns:
            List of news articles with title, link, snippet, and date
        """
        try:
            logger.info(f"Performing news search for: {query}")

            results = []
            news_results = self.ddgs.news(
                query,
                region=region,
                max_results=max_results
            )

            for result in news_results:
                results.append({
                    "title": result.get("title", ""),
                    "link": result.get("url", ""),
                    "snippet": result.get("body", ""),
                    "date": result.get("date", ""),
                    "source": result.get("source", ""),
                })

            logger.info(f"Found {len(results)} news results")
            return results

        except Exception as e:
            logger.error(f"Error performing news search: {e}")
            return []

    def search_sync(
        self,
        query: str,
        max_results: int = 5,
        region: str = "wt-wt",
        safesearch: str = "moderate"
    ) -> List[Dict[str, Any]]:
        """
        Synchronous version of search for non-async contexts

        Args:
            query: Search query string
            max_results: Maximum number of results to return
            region: Region for search (default: worldwide)
            safesearch: Safe search setting (off, moderate, strict)

        Returns:
            List of search results with title, link, and snippet
        """
        try:
            logger.info(f"Performing web search (sync) for: {query}")

            results = []
            search_results = self.ddgs.text(
                query,
                region=region,
                safesearch=safesearch,
                max_results=max_results
            )

            for result in search_results:
                results.append({
                    "title": result.get("title", ""),
                    "link": result.get("href", ""),
                    "snippet": result.get("body", ""),
                })

            logger.info(f"Found {len(results)} search results")
            return results

        except Exception as e:
            logger.error(f"Error performing web search: {e}")
            return []
