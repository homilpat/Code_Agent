package com.knowledge.blog.service;

import com.knowledge.blog.dto.PostCreateRequest;
import com.knowledge.blog.dto.RagQueryDto;
import com.knowledge.blog.mapper.CategoryMapper;
import com.knowledge.blog.mapper.PostMapper;
import com.knowledge.blog.model.Category;
import com.knowledge.blog.model.Post;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.web.util.HtmlUtils;
import org.springframework.web.reactive.function.client.WebClient;

import java.util.List;
import java.util.HashSet;
import java.util.Set;

@Slf4j
@Service
@RequiredArgsConstructor
public class PostService {

    private final PostMapper postMapper;
    private final CategoryMapper categoryMapper;
    private final WebClient.Builder webClientBuilder;
    private final ImageStorageService imageStorageService;

    @Value("${rag.fastapi-url}")
    private String fastApiUrl;

    public List<Post> getPosts(String section, Long categoryId) {
        return postMapper.findAll(section, categoryId);
    }

    public Post getPostById(Long id) {
        postMapper.incrementViewCount(id);
        return postMapper.findById(id);
    }

    @Transactional
    public Post createPost(PostCreateRequest req) {
        Category category = categoryMapper.findById(req.getCategoryId());
        if (category == null) {
            throw new IllegalArgumentException("존재하지 않는 카테고리입니다.");
        }

        Post post = new Post();
        post.setCategoryId(req.getCategoryId());
        post.setTitle(req.getTitle());
        post.setSummary(req.getSummary());
        post.setContent(req.getContent());
        post.setTags(req.getTags());
        post.setAuthorId(1L);
        post.setIsPublished(true);

        post.setKeyPoints(req.getKeyPoints());
        post.setLearningDirections(req.getLearningDirections());
        postMapper.insert(post);

        indexPostToRag(post, category);

        return postMapper.findById(post.getId());
    }

    @Transactional
    public Post updatePost(Long id, PostCreateRequest req) {
        Post post = postMapper.findById(id);
        if (post == null) {
            return null;
        }
        Category category = categoryMapper.findById(req.getCategoryId());
        if (category == null) {
            throw new IllegalArgumentException("존재하지 않는 카테고리입니다.");
        }

        Set<String> removedImages = new HashSet<>(imageStorageService.findManagedImages(post.getContent()));
        removedImages.removeAll(imageStorageService.findManagedImages(req.getContent()));

        post.setCategoryId(req.getCategoryId());
        post.setTitle(req.getTitle());
        post.setSummary(req.getSummary());
        post.setContent(req.getContent());
        post.setTags(req.getTags());
        post.setKeyPoints(req.getKeyPoints());
        post.setLearningDirections(req.getLearningDirections());
        postMapper.update(post);
        cleanupImagesAfterCommit(removedImages, id);
        postMapper.updateRagIndexStatus(id, false);
        deleteSourceFromRag(id);
        indexPostToRag(post, category);
        return postMapper.findById(id);
    }

    @Transactional
    public boolean deletePost(Long id) {
        Post post = postMapper.findById(id);
        if (post == null) {
            return false;
        }
        Set<String> postImages = imageStorageService.findManagedImages(post.getContent());
        deleteSourceFromRag(id);
        postMapper.delete(id);
        cleanupImagesAfterCommit(postImages, null);
        return true;
    }

    public boolean reindexPost(Long id) {
        Post post = postMapper.findById(id);
        if (post == null) return false;
        Category category = categoryMapper.findById(post.getCategoryId());
        postMapper.updateRagIndexStatus(id, false);
        indexPostToRag(post, category);
        return true;
    }

    private void deleteSourceFromRag(Long postId) {
        webClientBuilder.baseUrl(fastApiUrl).build()
                .delete()
                .uri("/api/rag/source/POST/{id}", postId)
                .retrieve()
                .toBodilessEntity()
                .block();
    }

    private void indexPostToRag(Post post, Category category) {
        try {
            RagQueryDto.IndexReq indexReq = new RagQueryDto.IndexReq();
            indexReq.setSource_type("POST");
            indexReq.setSource_id(post.getId());
            indexReq.setTitle(post.getTitle());
            indexReq.setContent(toSearchableText(post.getContent()));
            indexReq.setCategory(category.getSection());
            indexReq.setTags(post.getTags());
            indexReq.setUrl("/posts/" + post.getId());
            indexReq.setVisibility(Boolean.TRUE.equals(post.getIsPublished()) ? "PUBLIC" : "PRIVATE");
            indexReq.setOwner_id(post.getAuthorId());

            webClientBuilder.baseUrl(fastApiUrl).build()
                    .post()
                    .uri("/api/rag/index")
                    .bodyValue(indexReq)
                    .retrieve()
                    .bodyToMono(String.class)
                    .doOnSuccess(res -> {
                        log.info("RAG Indexing Success for Post ID {}: {}", post.getId(), res);
                        postMapper.updateRagIndexStatus(post.getId(), true);
                    })
                    .doOnError(err -> {
                        postMapper.updateRagIndexStatus(post.getId(), false);
                        log.warn("RAG Indexing Failed for Post ID {}: {}", post.getId(), err.getMessage());
                    })
                    .subscribe();
        } catch (Exception e) {
            log.error("Failed to trigger RAG indexing", e);
        }
    }

    private String toSearchableText(String content) {
        if (content == null) return "";
        return HtmlUtils.htmlUnescape(content.replaceAll("<[^>]+>", " "))
                .replaceAll("\\s+", " ")
                .trim();
    }

    private void cleanupImagesAfterCommit(Set<String> candidates, Long excludePostId) {
        Set<String> unusedImages = candidates.stream()
                .filter(filename -> postMapper.countImageReferences(filename, excludePostId) == 0)
                .collect(java.util.stream.Collectors.toUnmodifiableSet());
        if (unusedImages.isEmpty()) return;

        Runnable cleanup = () -> unusedImages.forEach(filename -> {
            try {
                imageStorageService.delete(filename);
                log.info("Deleted unused post image {}", filename);
            } catch (Exception exception) {
                log.warn("Failed to delete unused post image {}: {}", filename, exception.getMessage());
            }
        });

        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    cleanup.run();
                }
            });
        } else {
            cleanup.run();
        }
    }
}
