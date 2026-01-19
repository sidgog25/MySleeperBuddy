"""
Tools for the agent to use.
"""
from langchain_core.tools import tool
from sqlalchemy import create_engine, text, Engine
import pandas as pd
from buddy import env
from langgraph.types import Command
from langchain_core.tools.base import InjectedToolCallId
from typing import Annotated
from langchain_core.messages import ToolMessage


class ServerSession:
    """A session for server-side state management and operations.

    In practice, this would be a separate service from where the agent is running and the agent would communicate with it using a REST API. In this simplified example, we use it to persist the db engine and data returned from the query_db tool.
    """

    def __init__(self):
        self.engine: Engine = None
        self.df: pd.DataFrame = None

        self.engine = self._get_engine()

    def _get_engine(self):
        if self.engine is None:
            # Configure SQLAlchemy for session pooling
            _engine = create_engine(
                env.SUPABASE_URL,
                pool_size=5,  # Smaller pool size since the pooler manages connections
                max_overflow=5,  # Fewer overflow connections needed
                pool_timeout=10,  # Shorter timeout for getting connections
                pool_recycle=1800,  # Recycle connections more frequently
                pool_pre_ping=True,  # Keep this to verify connections
                pool_use_lifo=True,  # Keep LIFO to reduce number of open connections
                connect_args={
                    "application_name": "MySleeperBuddy_agent",
                    "options": "-c statement_timeout=30000",
                    # Keepalives less important with transaction pooler but still good practice
                    "keepalives": 1,
                    "keepalives_idle": 60,
                    "keepalives_interval": 30,
                    "keepalives_count": 3
                }
            )
            return _engine
        return self.engine


# Create a global instance of the ServerSession
session = ServerSession()


@tool
def query_db(query: str) -> str:
    """Query the database using Postgres SQL.

    Args:
        query: The SQL query to execute. Must be a valid postgres SQL string that can be executed directly.

    Returns:
        str: The query result as a markdown table.
    """
    try:
        # Use the global engine in the server session to connect to Supabase
        with session.engine.connect().execution_options(
                isolation_level="READ COMMITTED"
        ) as conn:
            result = conn.execute(text(query))

            columns = list(result.keys())
            rows = result.fetchall()
            df = pd.DataFrame(rows, columns=columns)

            # Store the DataFrame in the server session
            session.df = df

            conn.close()  # Explicitly close the connection
        return df.to_markdown(index=False)
    except Exception as e:
        return f"Error executing query: {str(e)}"



