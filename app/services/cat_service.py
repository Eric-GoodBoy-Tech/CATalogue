from typing import List, Optional, Type, cast, ClassVar
from datetime import datetime, timezone
from sqlalchemy.orm import Query, DeclarativeBase
from .. import db
from ..models import Cat, User, CatImage
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename
import os
from flask import current_app, url_for
from .base_service import BaseService

class CatService(BaseService):
    """猫咪信息服务层"""
    def __init__(self, db):
        super().__init__(db)
        
    model: ClassVar[Type[Cat]] = Cat  # 定义模型类
    
    def get(self, model=None, id: Optional[int] = None) -> Optional[Cat]:  # type: ignore
        """获取单个猫咪信息"""
        model = model or self.model
        if id is None:
            return None
        return super().get(model, id)  # type: ignore
    
    def get_all(self, model: Optional[Type[Cat]] = None) -> List[Cat]:
        """获取所有猫咪信息"""
        return super().get_all(model or self.model)
    
    def get_cat(self, cat_id: int) -> Optional[Cat]:
        """获取单个猫咪信息
        参数:
            cat_id: 猫咪ID
        返回:
            找到的Cat对象或None
        """
        if not hasattr(self.db, 'session'):
            raise ValueError("db对象必须包含session属性")
            
        try:
            with self.db.session.begin_nested():
                cat = self.db.session.get(Cat, cat_id)
                if cat:
                    # 预加载关联数据
                    self.db.session.refresh(cat)
                return cat
        except Exception as e:
            current_app.logger.error(f"获取猫咪信息失败(ID:{cat_id}): {str(e)}")
            raise
    
    def get_all_cats(self) -> List[Cat]:
        """获取所有猫咪信息(按更新时间排序)
        返回:
            按更新时间降序排列的猫咪列表
        """
        if not hasattr(self.db, 'session'):
            raise ValueError("db对象必须包含session属性")
        if not hasattr(self.db.session, 'query'):
            raise ValueError("db.session必须支持query方法")
        return self.db.session.query(Cat).order_by(Cat.updated_at.desc()).all()
        
    def get_paginated_cats(self, page: int = 1, per_page: int = 10, **filters) -> dict:
        """分页获取猫咪信息
        参数:
            page: 页码(从1开始)
            per_page: 每页数量
            filters: 过滤条件
        返回:
            {
                'items': List[Cat],  # 当前页数据
                'total': int,         # 总记录数
                'pages': int,         # 总页数
                'current_page': int,  # 当前页码
                'per_page': int       # 每页数量
            }
        """
        if not hasattr(self.db, 'session'):
            raise ValueError("db对象必须包含session属性")
        if not hasattr(self.db.session, 'query'):
            raise ValueError("db.session必须支持query方法")
            
        query = self.db.session.query(Cat).order_by(Cat.updated_at.desc())
        for key, value in filters.items():
            if hasattr(Cat, key):
                query = query.filter(getattr(Cat, key) == value)
        
        total = query.count()
        items = query.offset((page - 1) * per_page).limit(per_page).all()
        pages = (total + per_page - 1) // per_page
        
        return {
            'items': items,
            'total': total,
            'pages': pages,
            'current_page': page,
            'per_page': per_page
        }
        
    def get_recent_cats(self, limit: int = 3) -> List[Cat]:
        """获取最近添加的猫咪(包含品种筛选)
        参数:
            limit: 返回的记录数限制
        返回:
            按创建时间降序排列的猫咪列表
        """
        if not hasattr(self.db, 'session'):
            raise ValueError("db对象必须包含session属性")
        if not hasattr(self.db.session, 'query'):
            raise ValueError("db.session必须支持query方法")
        return self.db.session.query(Cat).order_by(Cat.created_at.desc()).limit(limit).all()
    
    def create(self, images: Optional[List[FileStorage]] = None, **kwargs) -> Cat:
        """创建猫咪信息(支持多图上传)"""
        if 'user_id' not in kwargs:
            raise ValueError("user_id是必填字段")
            
        user_id = kwargs['user_id']
        if not self.db.session.get(User, user_id):
            raise ValueError(f"用户ID {user_id} 不存在")
            
        if 'name' not in kwargs:
            raise ValueError("name是必填字段")
            
        # 确保必填字段存在
        required_fields = {
            'name': kwargs['name'],
            'user_id': user_id,
            'created_at': datetime.now(timezone.utc),
            'updated_at': datetime.now(timezone.utc)
        }
        
        # 合并参数
        create_kwargs = {**required_fields, **kwargs}
        current_app.logger.debug(f"创建猫咪参数: {create_kwargs}")
        
        try:
            cat = cast(Cat, super().create(self.model, **create_kwargs))
        except Exception as e:
            current_app.logger.error(f"创建猫咪失败: {str(e)}")
            raise
        
        if images:
            self._handle_images(cat.id, images)
            
        return cat
    
    def _handle_images(self, cat_id: int, images: List[FileStorage]) -> None:
        """处理猫咪图片上传"""
        if not images:
            return

        max_size = current_app.config.get('MAX_IMAGE_SIZE', 5 * 1024 * 1024)  # 默认5MB
        
        try:
            for i, image in enumerate(images):
                # 检查文件大小
                image.seek(0, 2)  # 移动到文件末尾
                file_size = image.tell()
                image.seek(0)  # 重置文件指针
                
                if file_size > max_size:
                    raise ValueError(f"图片大小超过限制({max_size/1024/1024:.1f}MB)")
                if not image or not image.filename or not image.content_type:
                    continue

                if not image.content_type.startswith('image/'):
                    raise ValueError("只允许上传图片文件")

                filename = secure_filename(str(image.filename))
                if not filename:
                    continue
                    
                upload_folder = current_app.config.get('UPLOAD_FOLDER')
                if not upload_folder:
                    raise ValueError("上传目录未配置")
                    
                save_path = os.path.join(str(upload_folder), filename)
                image.save(save_path)

                self.db.session.add(CatImage(
                    url=f"/static/uploads/{filename}",
                    is_primary=(i == 0),
                    cat_id=cat_id,
                    created_at=datetime.now(timezone.utc)
                ))
            
            self.db.session.commit()
        except Exception as e:
            self.db.session.rollback()
            current_app.logger.error(f"图片上传失败: {str(e)}")
            raise
    
    def update(self, model: Type[Cat], id: int, **kwargs) -> Optional[Cat]:
        """更新猫咪信息
        参数:
            model: 模型类
            id: 猫咪ID
            kwargs: 更新数据，可包含:
                images: 可选，要更新的图片列表
                其他字段更新值
        """
        images = kwargs.pop('images', None)
        try:
            cat = self.db.session.get(Cat, id)
            if not cat:
                return None
                
            self.db.session.begin_nested()
            
            for key, value in kwargs.items():
                if hasattr(cat, key):
                    setattr(cat, key, value)
            cat.updated_at = datetime.now(timezone.utc)
            
            if images:
                for image in list(cat.images if cat.images else []):  # type: ignore
                    static_folder = current_app.static_folder
                    if not static_folder or not image.url:
                        continue
                    image_path = os.path.join(str(static_folder), str(image.url).lstrip('/static/'))
                    if os.path.exists(image_path):
                        try:
                            os.remove(image_path)
                        except Exception as e:
                            current_app.logger.error(f"删除图片文件失败: {str(e)}")
                    self.db.session.delete(image)
                
                for i, image in enumerate(images):
                    if not image:
                        continue
                        
                    filename = secure_filename(str(image.filename))
                    upload_folder = current_app.config.get('UPLOAD_FOLDER')
                    if not upload_folder:
                        raise ValueError("上传目录未配置")
                    save_path = os.path.join(str(upload_folder), filename)
                    image.save(save_path)
                    
                    self.db.session.add(CatImage(
                        url=f"/static/uploads/{filename}",
                        is_primary=(i == 0),
                        cat_id=cat.id
                    ))
            
            self.db.session.commit()
            return cat
            
        except Exception as e:
            self.db.session.rollback()
            current_app.logger.error(f"更新猫咪失败: {str(e)}")
            raise
    
    def delete(self, id: int) -> bool:
        """删除猫咪信息"""
        try:
            cat = self.db.session.get(self.model, id)
            if not cat:
                current_app.logger.warning(f"尝试删除不存在的猫咪ID: {id}")
                return False
                
            # 删除关联图片
            for image in list(cat.images if cat.images else []):  # type: ignore
                try:
                    if image.url:
                        image_path = os.path.join(
                            str(current_app.static_folder), 
                            str(image.url).lstrip('/static/'))
                        if os.path.exists(image_path):
                            os.remove(image_path)
                except Exception as e:
                    current_app.logger.error(f"删除图片文件失败: {str(e)}")
                    continue
            
            # 删除猫咪记录
            self.db.session.delete(cat)
            self.db.session.commit()
            return True
            
        except Exception as e:
            self.db.session.rollback()
            current_app.logger.error(f"删除猫咪失败(ID:{id}): {str(e)}", exc_info=True)
            return False
    
    def create_cat(self, user_id: int, images=None, **kwargs) -> Cat:
        """创建猫咪信息(兼容旧接口)
        参数:
            user_id: 必须提供用户ID
            images: 可选，图片列表
            **kwargs: 其他猫咪属性
        返回:
            创建的Cat对象
        """
        if not user_id:
            raise ValueError("user_id is required")
            
        kwargs['user_id'] = user_id
        
        # 检查名称是否已存在
        with self.db.session.begin_nested():
            if 'name' in kwargs and self.db.session.query(Cat).filter_by(name=kwargs['name']).first():
                raise ValueError(f"猫咪名称'{kwargs['name']}'已存在")
            
        try:
            return self.create(images=images, **kwargs)
        except Exception as e:
            self.db.session.rollback()
            current_app.logger.error(f"创建猫咪失败: {str(e)}")
            raise
    
    def update_cat(self, cat_id: int, **update_data) -> Optional[Cat]:
        """更新猫咪信息(兼容旧接口)"""
        return self.update(self.model, cat_id, **update_data)
    
    def delete_cat(self, cat_id: int) -> bool:
        """删除猫咪信息(兼容旧接口)"""
        return self.delete(cat_id)
    
    def search_cats(self, keyword: Optional[str] = None, breed: Optional[str] = None, 
                   min_age: Optional[int] = None, max_age: Optional[int] = None,
                   is_adopted: Optional[bool] = None) -> List[Cat]:
        """搜索猫咪信息"""
        query = self.db.session.query(Cat)
        
        if keyword:
            query = query.filter(
                self.db.or_(
                    Cat.name.ilike(f'%{keyword}%'),
                    Cat.description.ilike(f'%{keyword}%')
                )
            )
        
        if breed:
            query = query.filter(Cat.breed.ilike(f'%{breed}%'))
            
        if min_age is not None:
            query = query.filter(Cat.age >= min_age)
        if max_age is not None:
            query = query.filter(Cat.age <= max_age)
            
        if is_adopted is not None:
            query = query.filter(Cat.is_adopted == is_adopted)
            
        return query.order_by(Cat.updated_at.desc()).all()
            
    def get_cats_by_breed(self, breed: str) -> List[Cat]:
        """按品种筛选猫咪(兼容旧接口)"""
        return self.search_cats(breed=breed)
        
    def get_adoptable_cats(self) -> List[Cat]:
        """获取可领养的猫咪(兼容旧接口)"""
        return self.search_cats(is_adopted=False)
        
    def validate_image_urls(self):
        """校验并修复数据库中的图片URL"""
        from ..models import CatImage
        invalid_urls = []
        
        try:
            images = self.db.session.query(CatImage).all()
            for image in images:
                if not image.url:
                    continue
                    
                if image.url.count('/static/uploads/') > 1:
                    original_url = image.url
                    image.url = '/static/uploads/' + image.url.split('/static/uploads/')[-1]
                    self.db.session.commit()
                    invalid_urls.append((original_url, image.url))
                    
            return invalid_urls
            
        except Exception as e:
            current_app.logger.error(f"校验图片URL时出错: {str(e)}", exc_info=True)
            raise

    def get_cat_stats(self) -> dict:
        """获取猫咪统计信息
        返回:
            {
                'total': int,               # 猫咪总数
                'by_breed': dict,           # 按品种统计
                'by_adoption': dict,        # 按领养状态统计
                'age_distribution': dict    # 年龄分布
            }
        """
        stats = {
            'total': 0,
            'by_breed': {},
            'by_adoption': {
                'adopted': 0,
                'not_adopted': 0
            },
            'age_distribution': {
                'kitten': 0,    # 0-1岁
                'young': 0,     # 1-3岁
                'adult': 0,     # 3-7岁
                'senior': 0     # 7岁以上
            }
        }

        try:
            # 获取总数
            stats['total'] = self.db.session.query(Cat).count()

            # 按品种统计
            breed_counts = self.db.session.query(
                Cat.breed,
                db.func.count(Cat.id)
            ).group_by(Cat.breed).all()
            stats['by_breed'] = {breed: count for breed, count in breed_counts}

            # 按领养状态统计
            adoption_counts = self.db.session.query(
                Cat.is_adopted,
                db.func.count(Cat.id)
            ).group_by(Cat.is_adopted).all()
            for is_adopted, count in adoption_counts:
                key = 'adopted' if is_adopted else 'not_adopted'
                stats['by_adoption'][key] = count

            # 年龄分布统计
            age_case = db.case(
                (Cat.age < 1, 'kitten'),
                (Cat.age < 3, 'young'),
                (Cat.age < 7, 'adult'),
                (db.true(), 'senior'),
                else_='unknown'
            )
            age_ranges = self.db.session.query(
                age_case,
                db.func.count(Cat.id)
            ).group_by(age_case).all()
            stats['age_distribution'] = {age_range: count for age_range, count in age_ranges}

            return stats

        except Exception as e:
            current_app.logger.error(f"获取猫咪统计信息失败: {str(e)}")
            raise
