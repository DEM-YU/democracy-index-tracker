"""Authentication router: registration, login, and watchlist management."""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import ALGORITHM, create_access_token, get_password_hash, verify_password
from app.database import get_db
from app.models import Country, User
from app.schemas import CountryResponse, Token, TokenData, UserCreate, UserResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


# ---------------------------------------------------------------------------
# Shared dependencies
# ---------------------------------------------------------------------------


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Decode the JWT and return the matching User row.

    Raises:
        HTTPException 401: If the token is invalid, expired, or the user no
            longer exists in the database.
    """
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        username: str | None = payload.get("sub")
        if username is None:
            raise credentials_exc
        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exc

    user = db.query(User).filter(User.username == token_data.username).first()
    if user is None:
        raise credentials_exc
    return user


def get_current_admin_user(current_user: User = Depends(get_current_user)) -> User:
    """Gate access to admin-only endpoints.

    Raises:
        HTTPException 403: If the authenticated user is not an admin.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return current_user


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(user_in: UserCreate, db: Session = Depends(get_db)) -> User:
    """Create a new user account.

    Raises:
        HTTPException 409: If *username* is already taken.
    """
    if db.query(User).filter(User.username == user_in.username).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{user_in.username}' is already registered",
        )
    user = User(
        username=user_in.username,
        hashed_password=get_password_hash(user_in.password),
        is_admin=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> Token:
    """Authenticate with username + password and return a Bearer token.

    Raises:
        HTTPException 401: If credentials are incorrect.
    """
    user = db.query(User).filter(User.username == form_data.username).first()
    if user is None or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(subject=user.username)
    return Token(access_token=access_token, token_type="bearer")


# ---------------------------------------------------------------------------
# Watchlist routes
# ---------------------------------------------------------------------------


@router.get("/me/watchlist", response_model=list[CountryResponse])
def get_watchlist(current_user: User = Depends(get_current_user)) -> list[Country]:
    """Return the list of countries the current user has bookmarked."""
    return current_user.watchlist


@router.post("/me/watchlist/{country_name}", response_model=CountryResponse)
def add_to_watchlist(
    country_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Country:
    """Add a country to the current user's watchlist.

    Raises:
        HTTPException 404: If no country with *country_name* exists.
        HTTPException 409: If the country is already in the watchlist.
    """
    country = db.query(Country).filter(Country.name == country_name).first()
    if country is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Country '{country_name}' not found",
        )
    if country in current_user.watchlist:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"'{country_name}' is already in your watchlist",
        )
    current_user.watchlist.append(country)
    db.commit()
    db.refresh(country)
    return country


@router.delete("/me/watchlist/{country_name}", status_code=status.HTTP_204_NO_CONTENT)
def remove_from_watchlist(
    country_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Remove a country from the current user's watchlist.

    Raises:
        HTTPException 404: If *country_name* is not in the watchlist.
    """
    country = next(
        (c for c in current_user.watchlist if c.name == country_name),
        None,
    )
    if country is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{country_name}' is not in your watchlist",
        )
    current_user.watchlist.remove(country)
    db.commit()
